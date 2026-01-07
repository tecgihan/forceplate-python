"""
フォースプレート用FTDI USB通信モジュール
"""

import ftd2xx
import ftd2xx.defines as ftd_defines
from typing import List, Optional
import time


class FTDICommunication:
    """FTDI USB通信管理クラス"""

    # デバイス定数
    DEVICE_NAME = "FORCEPLATE CONTROLLER"
    BAUDRATE = 1000000
    LATENCY = 1  # レイテンシタイマー (ms)
    IN_TRANSFER_SIZE = 64 * 1024  # 受信バッファサイズ
    TX_TIMEOUT = 1000  # 送信タイムアウト (ms)
    RX_TIMEOUT = 1000  # 受信タイムアウト (ms)

    def __init__(self):
        self.device: Optional[ftd2xx.FTD2XX] = None
        self.device_index: int = -1
        self.serial_number: str = ""

    def list_devices(self) -> List[dict]:
        """
        接続されているFTDIデバイスをリスト表示

        Returns:
            List[dict]: デバイス情報のリスト
                - index: デバイスインデックス
                - serial: シリアル番号
                - description: デバイス説明
        """
        device_list = []

        try:
            num_devices = ftd2xx.createDeviceInfoList()

            for i in range(num_devices):
                try:
                    info = ftd2xx.getDeviceInfoDetail(i)
                    device_info = {
                        'index': info['index'],
                        'serial': info['serial'].decode('utf-8') if isinstance(info['serial'], bytes) else info['serial'],
                        'description': info['description'].decode('utf-8') if isinstance(info['description'], bytes) else info['description'],
                        'flags': info['flags']
                    }
                    device_list.append(device_info)
                except Exception as e:
                    print(f"デバイス {i} 情報取得エラー: {e}")

        except Exception as e:
            print(f"デバイスリスト取得エラー: {e}")

        return device_list

    def list_fp_devices(self) -> List[dict]:
        """
        フォースプレートデバイスのみをリスト表示

        Returns:
            List[dict]: フォースプレートデバイス情報のリスト
        """
        all_devices = self.list_devices()
        fp_devices = [d for d in all_devices if self.DEVICE_NAME in d.get('description', '')]
        return fp_devices

    def open_device(self, index: int = 0) -> bool:
        """
        デバイスをインデックスで開く

        Args:
            index: デバイスインデックス

        Returns:
            bool: 成功した場合True
        """
        try:
            # 既存の接続があれば閉じる
            if self.device is not None:
                self.close_device()

            # デバイスを開く
            self.device = ftd2xx.open(index)

            # デバイス設定
            self._configure_device()

            self.device_index = index
            return True

        except ftd2xx.DeviceError as e:
            print(f"デバイスオープンエラー: {e}")
            return False
        except Exception as e:
            print(f"予期しないエラー: {e}")
            return False

    def open_device_by_serial(self, serial: str) -> bool:
        """
        デバイスをシリアル番号で開く

        Args:
            serial: シリアル番号

        Returns:
            bool: 成功した場合True
        """
        try:
            # 既存の接続があれば閉じる
            if self.device is not None:
                self.close_device()

            # シリアル番号でデバイスを開く
            self.device = ftd2xx.openEx(serial.encode('utf-8'), ftd_defines.OPEN_BY_SERIAL_NUMBER)

            # デバイス設定
            self._configure_device()

            self.serial_number = serial
            return True

        except ftd2xx.DeviceError as e:
            print(f"デバイスオープンエラー: {e}")
            return False
        except Exception as e:
            print(f"予期しないエラー: {e}")
            return False

    def _configure_device(self):
        """デバイスの設定を行う"""
        if self.device is None:
            return

        # ボーレート設定
        self.device.setBaudRate(self.BAUDRATE)

        # データ特性設定 (8bit, 1 stop bit, no parity)
        self.device.setDataCharacteristics(
            ftd_defines.BITS_8,
            ftd_defines.STOP_BITS_1,
            ftd_defines.PARITY_NONE
        )

        # フロー制御設定 (RTS/CTS)
        self.device.setFlowControl(ftd_defines.FLOW_RTS_CTS, 0, 0)

        # タイムアウト設定
        self.device.setTimeouts(self.RX_TIMEOUT, self.TX_TIMEOUT)

        # レイテンシタイマー設定
        self.device.setLatencyTimer(self.LATENCY)

        # USB転送サイズ設定
        self.device.setUSBParameters(self.IN_TRANSFER_SIZE, self.IN_TRANSFER_SIZE)

        # バッファクリア
        self.device.purge(ftd_defines.PURGE_RX | ftd_defines.PURGE_TX)

        # 少し待機
        time.sleep(0.1)

    def close_device(self) -> bool:
        """
        デバイスを閉じる

        Returns:
            bool: 成功した場合True
        """
        try:
            if self.device is not None:
                # バッファをパージ
                self.device.purge(ftd_defines.PURGE_RX | ftd_defines.PURGE_TX)
                # デバイスを閉じる
                self.device.close()
                self.device = None
                self.device_index = -1
                self.serial_number = ""
                return True
            return False

        except Exception as e:
            print(f"デバイスクローズエラー: {e}")
            return False

    def is_open(self) -> bool:
        """
        デバイスが開いているか確認

        Returns:
            bool: 開いている場合True
        """
        return self.device is not None

    def write_bytes(self, data: bytes) -> bool:
        """
        バイトデータを送信

        Args:
            data: 送信するバイトデータ

        Returns:
            bool: 成功した場合True
        """
        if not self.is_open():
            return False

        try:
            written = self.device.write(data)
            return written == len(data)

        except ftd2xx.DeviceError as e:
            print(f"書き込みエラー: {e}")
            return False
        except Exception as e:
            print(f"書き込みエラー: {e}")
            return False

    def read_bytes(self, size: int = 1) -> Optional[bytes]:
        """
        指定バイト数読み込み

        Args:
            size: 読み込むバイト数

        Returns:
            bytes: 読み込んだデータ、エラー時はNone
        """
        if not self.is_open():
            return None

        try:
            data = self.device.read(size)
            return data if data else None

        except ftd2xx.DeviceError as e:
            print(f"読み込みエラー: {e}")
            return None
        except Exception as e:
            print(f"読み込みエラー: {e}")
            return None

    def read_available(self) -> Optional[bytes]:
        """
        受信バッファにあるデータをすべて読み込み

        Returns:
            bytes: 読み込んだデータ、エラー時はNone
        """
        if not self.is_open():
            return None

        try:
            rx_queue, tx_queue, event_status = self.device.getStatus()
            if rx_queue > 0:
                return self.device.read(rx_queue)
            return b''

        except Exception as e:
            print(f"読み込みエラー: {e}")
            return None

    def get_bytes_in_buffer(self) -> int:
        """
        受信バッファのバイト数を取得

        Returns:
            int: バッファ内のバイト数
        """
        if not self.is_open():
            return 0

        try:
            rx_queue, tx_queue, event_status = self.device.getStatus()
            return rx_queue
        except Exception as e:
            print(f"受信キュー取得エラー: {e}")
            return 0

    def clear_buffers(self):
        """入出力バッファをクリア"""
        if self.is_open():
            try:
                self.device.purge(ftd_defines.PURGE_RX | ftd_defines.PURGE_TX)
            except Exception as e:
                print(f"バッファクリアエラー: {e}")

    def set_timeout(self, rx_timeout: int, tx_timeout: int):
        """
        タイムアウト時間を設定

        Args:
            rx_timeout: 受信タイムアウト (ms)
            tx_timeout: 送信タイムアウト (ms)
        """
        if self.is_open():
            self.device.setTimeouts(rx_timeout, tx_timeout)

    def get_device_info(self) -> Optional[dict]:
        """
        接続中のデバイス情報を取得

        Returns:
            dict: デバイス情報、未接続時はNone
        """
        if not self.is_open():
            return None

        try:
            info = self.device.getDeviceInfo()
            return {
                'type': info['type'],
                'id': info['id'],
                'description': info['description'].decode('utf-8') if isinstance(info['description'], bytes) else info['description'],
                'serial': info['serial'].decode('utf-8') if isinstance(info['serial'], bytes) else info['serial']
            }
        except Exception as e:
            print(f"デバイス情報取得エラー: {e}")
            return None

    def get_library_version(self) -> Optional[str]:
        """
        FTD2XXライブラリのバージョンを取得

        Returns:
            str: バージョン文字列
        """
        try:
            version = ftd2xx.getLibraryVersion()
            major = (version >> 16) & 0xFF
            minor = (version >> 8) & 0xFF
            build = version & 0xFF
            return f"{major}.{minor}.{build}"
        except Exception as e:
            print(f"ライブラリバージョン取得エラー: {e}")
            return None


# テスト用コード
if __name__ == "__main__":
    comm = FTDICommunication()

    # ライブラリバージョン表示
    lib_version = comm.get_library_version()
    if lib_version:
        print(f"FTD2XX ライブラリバージョン: {lib_version}")

    # 利用可能なデバイスを表示
    print("\n接続されているFTDIデバイス:")
    devices = comm.list_devices()
    for dev in devices:
        print(f"  [{dev['index']}] {dev['description']} (Serial: {dev['serial']})")

    # フォースプレートデバイスのみを表示
    print(f"\n{comm.DEVICE_NAME}デバイス:")
    fp_devices = comm.list_fp_devices()
    for dev in fp_devices:
        print(f"  [{dev['index']}] {dev['description']} (Serial: {dev['serial']})")
