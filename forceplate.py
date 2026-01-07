"""
フォースプレートデバイス制御クラス
"""

import threading
import time
from enum import IntEnum
from typing import Optional, Callable, List
from dataclasses import dataclass, field
import numpy as np

from ftdi_comm import FTDICommunication
from packet_parser import PacketParser, Range, Frequency, OutCh, EngCh, get_matome_for_frequency


class RmtStatus(IntEnum):
    """リモコンステータス"""
    NO_DEVICE = 0   # 未接続
    IDLE = 1        # 待機中
    EXT = 2         # 外部トリガ待ち受け中
    MEASURE = 3     # 測定中
    ZERO = 4        # ゼロ調整中
    LEVEL = 5       # レベルトリガ待受中
    MEASURE_8CH = 6 # 測定中（8chモード）
    MEASURE_12CH = 7 # 測定中（12chモード）
    SLEEP = 8       # スリープ中
    ERROR = 9       # エラー発生


class AmpStatus(IntEnum):
    """アンプステータス"""
    NO_DEVICE = 0
    INITIALIZE = 1
    IDLE = 2
    EXT = 3
    MEASURE = 4
    ZERO = 5
    ERROR = 6


@dataclass
class AmpInfo:
    """アンプ情報"""
    serial: int = 0
    version: str = ""
    status: AmpStatus = AmpStatus.NO_DEVICE
    ch_count: int = 8
    is_12ch_enable: bool = False
    az0: float = 0.0  # センサ中心～FP上面 [m]
    # フルスケール値 [range, ch]
    fs: np.ndarray = None

    def __post_init__(self):
        if self.fs is None:
            # デフォルトのフルスケール値
            self.fs = np.array([
                [1500, 1500, 3000, 300, 300, 200],   # R3K
                [3000, 3000, 6000, 600, 600, 400],   # R6K
                [5000, 5000, 10000, 1000, 1000, 600] # R10K
            ], dtype=np.float64)


@dataclass
class RmtInfo:
    """リモコン情報"""
    serial: int = 0
    version: str = ""


class ForcePlate:
    """フォースプレートデバイス制御クラス"""

    # 定数
    DEVICE_NAME = "FORCEPLATE CONTROLLER"
    REPLY_TIMEOUT = 1.0  # 秒
    CH_COUNT = 6
    MAX_FP_COUNT = 20
    MATOME_DEFAULT = 100

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        """
        初期化

        Args:
            log_callback: ログ出力コールバック関数
        """
        self._comm = FTDICommunication()
        self._parser = PacketParser()
        self._status = RmtStatus.NO_DEVICE
        self._rmt_info = RmtInfo()
        self._amp_info: List[AmpInfo] = []
        self._fp_count = 0

        self._frequency = Frequency.F1000
        self._range = Range.R3K
        self._matome = self.MATOME_DEFAULT

        self._log_callback = log_callback

        # データバッファ
        self._buffer_size = self.CH_COUNT * 2 * 10000 * 600  # 10分間分
        self._data_buffer = bytearray(self._buffer_size)
        self._read_ptr = 0
        self._write_ptr = 0
        self._data_count = 0
        self._packet_size = 0

        # スレッド関連
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._data_lock = threading.Lock()

        # エラー情報
        self._errors: List[str] = []

    def _log(self, message: str):
        """ログ出力"""
        if self._log_callback:
            self._log_callback(message)
        else:
            print(f"[ForcePlate] {message}")

    @property
    def status(self) -> RmtStatus:
        """ステータス取得"""
        return self._status

    @property
    def rmt_info(self) -> RmtInfo:
        """リモコン情報取得"""
        return self._rmt_info

    @property
    def fp_count(self) -> int:
        """接続FP台数"""
        return self._fp_count

    @property
    def frequency(self) -> Frequency:
        """測定周波数"""
        return self._frequency

    @property
    def range(self) -> Range:
        """測定レンジ"""
        return self._range

    @property
    def matome(self) -> int:
        """まとめ数"""
        return self._matome

    @property
    def data_count(self) -> int:
        """取得済みデータ数"""
        with self._data_lock:
            return self._data_count

    @property
    def is_connected(self) -> bool:
        """接続状態"""
        return self._status != RmtStatus.NO_DEVICE

    def amp(self, index: int) -> Optional[AmpInfo]:
        """
        アンプ情報取得

        Args:
            index: アンプインデックス

        Returns:
            AmpInfo: アンプ情報
        """
        if 0 <= index < len(self._amp_info):
            return self._amp_info[index]
        return None

    def list_devices(self) -> List[dict]:
        """
        フォースプレートデバイスをリスト

        Returns:
            List[dict]: デバイス情報のリスト
        """
        return self._comm.list_fp_devices()

    def connect(self, device_index: int = 0) -> bool:
        """
        デバイスに接続

        Args:
            device_index: デバイスインデックス

        Returns:
            bool: 成功時True
        """
        if self.is_connected:
            self._log("既に接続されています")
            return True

        self._log(f"デバイス {device_index} に接続中...")

        # フォースプレートデバイスを探す
        fp_devices = self._comm.list_fp_devices()
        if not fp_devices:
            self._log("フォースプレートデバイスが見つかりません")
            self._status = RmtStatus.NO_DEVICE
            return False

        if device_index >= len(fp_devices):
            self._log(f"デバイスインデックス {device_index} は範囲外です")
            self._status = RmtStatus.NO_DEVICE
            return False

        # デバイスを開く
        if not self._comm.open_device(fp_devices[device_index]['index']):
            self._log("デバイスのオープンに失敗しました")
            self._status = RmtStatus.NO_DEVICE
            return False

        # 初期化
        time.sleep(0.5)
        self._comm.clear_buffers()

        # STOPコマンド送信（念のため）
        self._send_command("STOP")
        time.sleep(0.5)
        self._comm.clear_buffers()

        # パラメータ取得
        if not self._get_all_parameters():
            self._log("パラメータ取得に失敗しました")
            self.disconnect()
            return False

        self._status = RmtStatus.IDLE
        self._log(f"接続成功: {self.DEVICE_NAME} (Serial: {self._rmt_info.serial})")
        return True

    def disconnect(self):
        """デバイスを切断"""
        if not self.is_connected:
            return

        self._log("切断中...")

        # 測定停止
        if self._status in [RmtStatus.MEASURE, RmtStatus.EXT, RmtStatus.LEVEL,
                            RmtStatus.MEASURE_8CH, RmtStatus.MEASURE_12CH]:
            self.stop()

        # スレッド停止
        self._stop_thread()

        # デバイス切断
        self._comm.close_device()
        self._status = RmtStatus.NO_DEVICE
        self._fp_count = 0
        self._amp_info = []
        self._log("切断完了")

    def start(self) -> bool:
        """
        測定開始

        Returns:
            bool: 成功時True
        """
        if self._status != RmtStatus.IDLE:
            self._log(f"測定開始できません（現在のステータス: {self._status.name}）")
            return False

        # データバッファクリア
        with self._data_lock:
            self._read_ptr = 0
            self._write_ptr = 0
            self._data_count = 0

        # パケットサイズ計算
        self._packet_size = self.CH_COUNT * 2 * self._matome * self._fp_count

        # FTDIバッファクリア
        self._comm.clear_buffers()

        # STARTコマンド送信（応答なし）
        if self._send_command("START"):
            self._status = RmtStatus.MEASURE
            self._start_thread()
            self._log("測定開始")
            return True
        else:
            self._log("STARTコマンド失敗")
            return False

    def stop(self) -> bool:
        """
        測定停止

        Returns:
            bool: 成功時True
        """
        if self._status not in [RmtStatus.MEASURE, RmtStatus.EXT, RmtStatus.LEVEL,
                                 RmtStatus.MEASURE_8CH, RmtStatus.MEASURE_12CH]:
            return True

        # スレッド停止
        self._stop_thread()

        # STOPコマンド送信
        self._send_command("STOP")
        time.sleep(0.1)
        self._comm.clear_buffers()

        self._status = RmtStatus.IDLE
        self._log("測定停止")
        return True

    def ext(self) -> bool:
        """
        外部トリガ待ちに移行

        Returns:
            bool: 成功時True
        """
        if self._status != RmtStatus.IDLE:
            self._log(f"外部トリガ待ちに移行できません（現在のステータス: {self._status.name}）")
            return False

        # データバッファクリア
        with self._data_lock:
            self._read_ptr = 0
            self._write_ptr = 0
            self._data_count = 0

        # パケットサイズ計算
        self._packet_size = self.CH_COUNT * 2 * self._matome * self._fp_count

        # EXTコマンド送信（応答なし）
        if self._send_command("EXT"):
            self._status = RmtStatus.EXT
            self._start_thread()
            self._log("外部トリガ待ち開始")
            return True
        else:
            self._log("EXTコマンド失敗")
            return False

    def level(self) -> bool:
        """
        レベルトリガ待ちに移行

        Returns:
            bool: 成功時True
        """
        if self._status != RmtStatus.IDLE:
            self._log(f"レベルトリガ待ちに移行できません（現在のステータス: {self._status.name}）")
            return False

        # データバッファクリア
        with self._data_lock:
            self._read_ptr = 0
            self._write_ptr = 0
            self._data_count = 0

        # パケットサイズ計算
        self._packet_size = self.CH_COUNT * 2 * self._matome * self._fp_count

        # LEVELコマンド送信（応答なし）
        if self._send_command("LEVEL"):
            self._status = RmtStatus.LEVEL
            self._start_thread()
            self._log("レベルトリガ待ち開始")
            return True
        else:
            self._log("LEVELコマンド失敗")
            return False

    def zero(self) -> bool:
        """
        ゼロ調整（完了まで待機、タイムアウト10秒）

        Returns:
            bool: 成功時True
        """
        if self._status != RmtStatus.IDLE:
            self._log(f"ゼロ調整できません（現在のステータス: {self._status.name}）")
            return False

        # ZEROコマンド送信（応答なし）
        if not self._send_command("ZERO"):
            self._log("ZEROコマンド失敗")
            return False

        self._status = RmtStatus.ZERO
        self._log("ゼロ調整開始")

        # FPにRX_OVERRUNが発生するのを防止するため待機
        time.sleep(1.0)

        # ステータスポーリングで完了を待つ（タイムアウト10秒）
        timeout = 10.0
        start_time = time.time()
        while time.time() - start_time < timeout:
            dev_status = self._get_device_status()
            if dev_status is None:
                time.sleep(0.1)
                continue

            if dev_status == RmtStatus.IDLE:
                self._status = RmtStatus.IDLE
                self._log("ゼロ調整完了")
                return True

            elif dev_status == RmtStatus.ERROR:
                self._status = RmtStatus.ERROR
                self._log("ゼロ調整エラー")
                return False

            time.sleep(0.1)

        # タイムアウト
        self._log("ゼロ調整タイムアウト")
        self._status = RmtStatus.ERROR
        return False

    def get_data(self) -> Optional[np.ndarray]:
        """
        測定データをAD値配列として取得

        Returns:
            np.ndarray: AD値配列 [fp_count, matome, channels]、データなしの場合None
        """
        with self._data_lock:
            if self._data_count == 0:
                return None

            # データ取得
            data = bytes(self._data_buffer[self._read_ptr:self._read_ptr + self._packet_size])
            if self._read_ptr + self._packet_size > self._buffer_size:
                # ラップアラウンド処理
                data = bytes(self._data_buffer[self._read_ptr:]) + \
                       bytes(self._data_buffer[:self._packet_size - (self._buffer_size - self._read_ptr)])

            self._read_ptr = (self._read_ptr + self._packet_size) % self._buffer_size
            self._data_count -= 1

        # AD値に変換
        return self._parser.bin_to_ad(data, self._matome, self._fp_count)

    def ad_to_eng(self, ad_values: np.ndarray, fp_index: int = 0,
                  az: float = None, fz_limit: float = 10.0) -> np.ndarray:
        """
        AD値を工学値に変換

        Args:
            ad_values: AD値配列 [matome, channels] または [fp_count, matome, channels]
            fp_index: FPインデックス（単一FPの場合に使用）
            az: FP上面～作用点までの距離（敷物の厚み）[mm]（Noneの場合は0）
            fz_limit: COP計算の荷重閾値 [N]

        Returns:
            np.ndarray: 工学値配列
        """
        # センサ中心～作用点 = |az0|（センサ中心～FP上面）+ az（FP上面～作用点）
        if fp_index < len(self._amp_info):
            amp = self._amp_info[fp_index]
            fs = amp.fs[self._range]
            az0_mm = abs(amp.az0) * 1000  # m -> mm（絶対値）
        else:
            fs = np.array([1500, 1500, 3000, 300, 300, 200])
            az0_mm = 0.0

        if az is None:
            az = 0.0
        total_az = az0_mm + az

        return self._parser.ad_to_eng(ad_values, self._range, fs, total_az, fz_limit)

    def set_frequency(self, frequency: Frequency) -> bool:
        """
        サンプリング周波数を設定

        Args:
            frequency: サンプリング周波数
        """
        if self._status != RmtStatus.IDLE:
            self._log("周波数設定はIdle状態でのみ可能です")
            return False

        freq_map = {
            Frequency.F10000: "10K",
            Frequency.F5000: "5K",
            Frequency.F2500: "2.5K",
            Frequency.F1000: "1K",
            Frequency.F500: "500",
            Frequency.F250: "250",
            Frequency.F240: "240",
            Frequency.F120: "120"
        }
        freq_str = freq_map.get(frequency, "1K")
        if self._send_command_with_reply(f"SPS_{freq_str}"):
            self._frequency = frequency
            self._matome = get_matome_for_frequency(frequency)
            self._log(f"周波数設定: {frequency.value}Hz, まとめ数: {self._matome}")
            return True
        return False

    def set_range(self, range_val: Range) -> bool:
        """
        測定レンジを設定

        Args:
            range_val: 測定レンジ
        """
        if self._status != RmtStatus.IDLE:
            self._log("レンジ設定はIdle状態でのみ可能です")
            return False

        # RANGEコマンドは応答なし
        range_names = {Range.R3K: "3kN", Range.R6K: "6kN", Range.R10K: "10kN"}
        if self._send_command(f"RANGE_{range_names[range_val]}"):
            # FPにRX_OVERRUNが発生するのを防止するため待機
            time.sleep(0.1)
            self._range = range_val
            self._parser.set_range(range_val)
            self._log(f"レンジ設定: {range_names[range_val]}")
            return True
        return False

    def discard_data(self):
        """データバッファをクリア"""
        with self._data_lock:
            self._read_ptr = 0
            self._write_ptr = 0
            self._data_count = 0

    # ----- 内部メソッド -----

    def _send_command(self, command: str) -> bool:
        """コマンド送信（終端文字: LFのみ）"""
        with self._lock:
            cmd = f"{command}\n".encode('ascii')
            return self._comm.write_bytes(cmd)

    def _send_command_with_reply(self, command: str, timeout: float = None) -> bool:
        """コマンド送信して応答を待つ"""
        if timeout is None:
            timeout = self.REPLY_TIMEOUT

        with self._lock:
            # バッファクリア
            self._comm.clear_buffers()

            # コマンド送信
            cmd = f"{command}\n".encode('ascii')
            if not self._comm.write_bytes(cmd):
                return False

            # 応答待ち
            # 応答形式: コマンドの最初の部分_OK (例: SPS_1K → SPS_OK, RANGE_3K → RANGE_OK)
            base_cmd = command.split("_")[0]  # SPS_1K → SPS, RANGE_3K → RANGE
            expected = f"{base_cmd}_OK"
            response = self._wait_response(timeout)

            if response and expected in response:
                return True
            else:
                self._log(f"コマンド応答エラー: 期待={expected}, 受信={response}")
                return False

    def _wait_response(self, timeout: float = None) -> Optional[str]:
        """応答を待つ"""
        if timeout is None:
            timeout = self.REPLY_TIMEOUT

        deadline = time.time() + timeout
        buffer = bytearray()

        while time.time() < deadline:
            data = self._comm.read_available()
            if data:
                buffer.extend(data)
                # 改行（LF）があれば応答として返す
                if b'\n' in buffer:
                    pos = buffer.index(b'\n')
                    response = buffer[:pos].decode('ascii', errors='ignore').strip()
                    return response
            time.sleep(0.001)

        if buffer:
            return buffer.decode('ascii', errors='ignore').strip()
        return None

    def _get_value(self, item: str) -> Optional[str]:
        """デバイスから値を取得"""
        with self._lock:
            # バッファクリア
            self._comm.clear_buffers()

            # コマンド送信
            cmd = f"{item}\n".encode('ascii')
            if not self._comm.write_bytes(cmd):
                return None

            # 応答待ち
            response = self._wait_response()
            if response is None:
                return None

            # 応答からプレフィックスを除去して値を取得
            # FPコマンドの場合
            if item.startswith("FP_"):
                if "_GET_" in item:
                    # FP_0106_GET_AZ0 → 応答は AZ0_値
                    fp_item = item.split("_GET_")[1]  # AZ0 など
                    prefix = f"{fp_item}_"
                elif "_GETFS" in item:
                    # FP_0106_GETFS → 応答は FS_値1,値2,...
                    prefix = "FS_"
                else:
                    # その他のFPコマンド
                    fp_item = item.split("_", 2)[2]  # FP_0106_XXX → XXX
                    prefix = f"{fp_item}_"
            else:
                # 通常のコマンド: "コマンド名_値"
                prefix = f"{item}_"

            if response.startswith(prefix):
                return response[len(prefix):]

            # プレフィックスがない場合はそのまま返す
            return response

    def _wake_device(self, timeout: float = 20.0) -> bool:
        """
        WAKEコマンドでデバイスを起動

        Args:
            timeout: タイムアウト秒数（デフォルト20秒）

        Returns:
            bool: 起動成功時True
        """
        if not self._send_command("WAKE"):
            self._log("WAKEコマンド送信失敗")
            return False

        # ステータスがIDLEになるまでポーリング
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(0.1)
            dev_status = self._get_device_status()
            if dev_status == RmtStatus.IDLE:
                self._log("デバイス起動完了")
                return True

        self._log("デバイス起動タイムアウト")
        return False

    def _get_device_status(self) -> Optional[RmtStatus]:
        """デバイスからステータスを取得"""
        with self._lock:
            # バッファクリア
            self._comm.clear_buffers()

            # STATEコマンド送信
            cmd = b"STATE\n"
            if not self._comm.write_bytes(cmd):
                return None

            # 応答待ち
            deadline = time.time() + self.REPLY_TIMEOUT
            buffer = bytearray()

            while time.time() < deadline:
                data = self._comm.read_available()
                if data:
                    buffer.extend(data)
                    if b'\r' in buffer or b'\n' in buffer:
                        break
                time.sleep(0.001)

            if not buffer:
                return None

            response = buffer.decode('ascii', errors='ignore').strip().upper()

            # レスポンス解析
            if response == "IDLE":
                return RmtStatus.IDLE
            elif response == "EXT":
                return RmtStatus.EXT
            elif response == "LEVEL":
                return RmtStatus.LEVEL
            elif response == "MEASURE":
                return RmtStatus.MEASURE
            elif response == "ZERO":
                return RmtStatus.ZERO
            elif response == "SLEEP":
                return RmtStatus.SLEEP
            elif response == "8AX":
                return RmtStatus.MEASURE_8CH
            elif response == "12AX":
                return RmtStatus.MEASURE_12CH
            elif "ERR" in response:
                return RmtStatus.ERROR

            return None

    def _get_all_parameters(self) -> bool:
        """全パラメータ取得"""
        # リモコンのステータス確認
        dev_status = self._get_device_status()
        if dev_status is None:
            self._log("ステータス取得失敗")
            # ステータス取得に失敗してもデフォルト値で続行
        elif dev_status == RmtStatus.SLEEP:
            # スリープ中の場合は起動
            self._log("スリープ中のため起動します...")
            if not self._wake_device(timeout=20.0):
                self._log("デバイス起動失敗")
                return False
        elif dev_status not in [RmtStatus.IDLE]:
            # IDLE以外の場合は停止
            self._send_command("STOP")
            time.sleep(0.5)

        # リモコン情報取得
        serial = self._get_value("SERIAL")
        if serial:
            try:
                self._rmt_info.serial = int(serial)
            except ValueError:
                pass

        version = self._get_value("VER")
        if version:
            self._rmt_info.version = version

        # 周波数取得
        freq = self._get_value("SPS")
        if freq:
            freq = freq.upper()
            if freq == "10K":
                self._frequency = Frequency.F10000
            elif freq == "5K":
                self._frequency = Frequency.F5000
            elif freq == "2.5K":
                self._frequency = Frequency.F2500
            elif freq == "1K":
                self._frequency = Frequency.F1000
            elif freq == "500":
                self._frequency = Frequency.F500
            elif freq == "250":
                self._frequency = Frequency.F250
            elif freq == "240":
                self._frequency = Frequency.F240
            elif freq == "120":
                self._frequency = Frequency.F120
            self._matome = get_matome_for_frequency(self._frequency)

        # レンジ取得
        range_str = self._get_value("RANGE")
        if range_str:
            range_str = range_str.upper()
            if "3K" in range_str:
                self._range = Range.R3K
            elif "6K" in range_str:
                self._range = Range.R6K
            elif "10K" in range_str:
                self._range = Range.R10K

        # FP台数取得
        fp_count = self._get_value("FPCOUNT")
        if fp_count:
            try:
                self._fp_count = int(fp_count)
            except ValueError:
                self._fp_count = 0

        # 各FPの情報取得
        self._amp_info = []
        for i in range(self._fp_count):
            amp = AmpInfo()

            # シリアル番号（FPSERIAL_0 形式）
            serial = self._get_value(f"FPSERIAL_{i}")
            if serial:
                try:
                    amp.serial = int(serial)
                except ValueError:
                    pass

            # シリアル番号が取得できたらFPから詳細パラメータを取得
            if amp.serial > 0:
                fp_prefix = f"FP_{amp.serial:04d}"

                # az0（センサ中心～FP上面）
                az0_val = self._get_value(f"{fp_prefix}_GET_AZ0")
                if az0_val:
                    try:
                        amp.az0 = float(az0_val)
                    except ValueError:
                        pass

                # フルスケール値（3レンジ×6ch = 18個、カンマ区切り）
                fs_val = self._get_value(f"{fp_prefix}_GETFS")
                if fs_val:
                    try:
                        fs_list = fs_val.split(",")
                        if len(fs_list) == 18:
                            for r in range(3):  # R3K, R6K, R10K
                                for ch in range(6):  # Fx, Fy, Fz, Mx, My, Mz
                                    amp.fs[r, ch] = float(fs_list[ch + r * 6])
                    except (ValueError, IndexError):
                        pass

            self._amp_info.append(amp)

        # FP台数が取得できなかった場合はデフォルト1台
        if self._fp_count == 0:
            self._fp_count = 1
            self._amp_info = [AmpInfo()]

        return True

    def _start_thread(self):
        """データ受信スレッド開始"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def _stop_thread(self):
        """データ受信スレッド停止"""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _receive_loop(self):
        """データ受信ループ（DTコマンドポーリング方式）"""
        packet_size = self._packet_size

        # 周波数に応じたタイムアウト設定
        freq_timeout = {
            Frequency.F10000: 0.2,
            Frequency.F5000: 0.4,
            Frequency.F2500: 0.8,
            Frequency.F1000: 2.0,
            Frequency.F500: 4.0,
            Frequency.F250: 8.0,
            Frequency.F240: 8.0,
            Frequency.F120: 16.0
        }
        read_timeout = freq_timeout.get(self._frequency, 2.0)

        recv_buffer = bytearray()

        try:
            is_first = True
            while self._running:
                # 最初以外はDTコマンドを送信（STARTで最初のデータは自動送信される）
                if not is_first:
                    if not self._comm.write_bytes(b"DT\n"):
                        self._log("DTコマンド送信失敗")
                        break

                # データ受信待ち
                deadline = time.time() + read_timeout
                while time.time() < deadline and self._running:
                    data = self._comm.read_available()
                    if data:
                        recv_buffer.extend(data)

                    # パケットサイズ分のデータが揃ったら処理
                    if len(recv_buffer) >= packet_size:
                        packet_data = bytes(recv_buffer[:packet_size])
                        recv_buffer = recv_buffer[packet_size:]

                        with self._data_lock:
                            # パケットをバッファに追加
                            for byte in packet_data:
                                self._data_buffer[self._write_ptr] = byte
                                self._write_ptr = (self._write_ptr + 1) % self._buffer_size
                            self._data_count += 1

                        is_first = False
                        break

                    time.sleep(0.001)
                else:
                    if self._running:
                        self._log(f"データ受信タイムアウト")

        except Exception as e:
            self._log(f"受信スレッドエラー: {e}")


# テスト用コード
if __name__ == "__main__":
    fp = ForcePlate()

    # デバイスリスト表示
    print("フォースプレートデバイス一覧:")
    devices = fp.list_devices()
    for dev in devices:
        print(f"  [{dev['index']}] Serial: {dev['serial']}")

    # 接続テスト
    # if devices:
    #     if fp.connect(0):
    #         print(f"\n接続成功:")
    #         print(f"  Serial: {fp.rmt_info.serial}")
    #         print(f"  Version: {fp.rmt_info.version}")
    #         print(f"  FP Count: {fp.fp_count}")
    #         print(f"  Frequency: {fp.frequency} Hz")
    #         print(f"  Range: {fp.range}")
    #
    #         fp.disconnect()
