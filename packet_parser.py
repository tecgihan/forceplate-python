"""
フォースプレート用パケット解析モジュール
"""

import struct
from enum import IntEnum
from typing import Optional
from dataclasses import dataclass
import numpy as np


class OutCh(IntEnum):
    """出力チャンネル定義（6ch）"""
    FX = 0  # 水平力X [N]
    FY = 1  # 水平力Y [N]
    FZ = 2  # 鉛直力 [N]
    MX = 3  # モーメントX [N*m]
    MY = 4  # モーメントY [N*m]
    MZ = 5  # モーメントZ [N*m]


class EngCh(IntEnum):
    """工学値チャンネル定義（6ch + 追加4ch）"""
    FX = 0   # 水平力X [N]
    FY = 1   # 水平力Y [N]
    FZ = 2   # 鉛直力 [N]
    MX = 3   # モーメントX [N*m]
    MY = 4   # モーメントY [N*m]
    MZ = 5   # モーメントZ [N*m]
    MXD = 6  # 作用面上モーメントX [N*m]
    MYD = 7  # 作用面上モーメントY [N*m]
    COP_X = 8  # 圧力中心X [mm]
    COP_Y = 9  # 圧力中心Y [mm]


class Range(IntEnum):
    """測定レンジ"""
    R3K = 0   # 3000N
    R6K = 1   # 6000N
    R10K = 2  # 10000N


class Frequency(IntEnum):
    """測定周波数"""
    F10000 = 10000
    F5000 = 5000
    F2500 = 2500
    F1000 = 1000
    F500 = 500
    F250 = 250
    F240 = 240
    F120 = 120


class PacketParser:
    """パケット解析クラス"""

    # 定数
    CH_COUNT = 6  # 出力チャンネル数
    BYTES_PER_SAMPLE = 2  # 16bit ADC

    def __init__(self):
        """初期化"""
        self._range = Range.R3K

    def set_range(self, range_val: Range):
        """測定レンジを設定"""
        self._range = range_val

    def bin_to_ad(self, data: bytes, matome: int, fp_count: int = 1) -> Optional[np.ndarray]:
        """
        バイナリデータをAD値配列に変換

        Args:
            data: バイナリデータ
            matome: まとめ数
            fp_count: フォースプレート台数

        Returns:
            np.ndarray: AD値配列 [fp_count, matome, channels]
        """
        if not data:
            return None

        # パケットサイズ: 6ch × 2byte × まとめ数 × FP台数
        packet_size = self.CH_COUNT * self.BYTES_PER_SAMPLE * matome * fp_count

        if len(data) < packet_size:
            return None

        # AD値配列
        ad_values = np.zeros((fp_count, matome, self.CH_COUNT), dtype=np.int16)

        offset = 0
        for fp in range(fp_count):
            for m in range(matome):
                for ch in range(self.CH_COUNT):
                    ad_values[fp, m, ch] = struct.unpack_from('<h', data, offset)[0]
                    offset += 2

        return ad_values

    def ad_to_eng(self, ad_values: np.ndarray, range_val: Range,
                  fs: np.ndarray, az: float = 0.0,
                  fz_limit: float = 10.0) -> np.ndarray:
        """
        AD値を工学値に変換

        Args:
            ad_values: AD値配列 [matome, channels] または [fp_count, matome, channels]
            range_val: 測定レンジ
            fs: フルスケール値配列 [channels]
            az: センサ中心～作用点までの距離 [mm]
            fz_limit: COP計算の荷重閾値 [N]

        Returns:
            np.ndarray: 工学値配列 [matome, eng_channels] または [fp_count, matome, eng_channels]
        """
        # 入力配列の次元を確認
        if ad_values.ndim == 2:
            # [matome, channels]
            return self._convert_single_fp(ad_values, range_val, fs, az, fz_limit)
        elif ad_values.ndim == 3:
            # [fp_count, matome, channels]
            fp_count = ad_values.shape[0]
            matome = ad_values.shape[1]
            eng_values = np.zeros((fp_count, matome, len(EngCh)), dtype=np.float64)
            for fp in range(fp_count):
                eng_values[fp] = self._convert_single_fp(
                    ad_values[fp], range_val, fs, az, fz_limit
                )
            return eng_values
        else:
            raise ValueError("ad_values must be 2D or 3D array")

    def _convert_single_fp(self, ad_values: np.ndarray, range_val: Range,
                           fs: np.ndarray, az: float,
                           fz_limit: float) -> np.ndarray:
        """
        単一FPのAD値を工学値に変換

        Args:
            ad_values: AD値配列 [matome, channels]
            range_val: 測定レンジ
            fs: フルスケール値配列 [channels]
            az: センサ中心～作用点までの距離 [mm]
            fz_limit: COP計算の荷重閾値 [N]

        Returns:
            np.ndarray: 工学値配列 [matome, eng_channels]
        """
        matome = ad_values.shape[0]
        eng_values = np.zeros((matome, len(EngCh)), dtype=np.float64)

        for i in range(matome):
            # AD値30000 = +フルスケール
            for ch in range(self.CH_COUNT):
                eng_values[i, ch] = ad_values[i, ch] * fs[ch] / 30000.0

            fx = eng_values[i, EngCh.FX]
            fy = eng_values[i, EngCh.FY]
            fz = eng_values[i, EngCh.FZ]
            mx = eng_values[i, EngCh.MX]
            my = eng_values[i, EngCh.MY]

            # 作用面上のモーメント
            # Mx' = Mx - Fy * az/1000
            # My' = My + Fx * az/1000
            mxd = mx - fy * (az / 1000.0)
            myd = my + fx * (az / 1000.0)
            eng_values[i, EngCh.MXD] = mxd
            eng_values[i, EngCh.MYD] = myd

            # COP計算（Fz >= FzLimit のとき）
            if fz >= fz_limit:
                # ax = -Myd / Fz * 1000 [mm]
                # ay = Mxd / Fz * 1000 [mm]
                eng_values[i, EngCh.COP_X] = -myd / fz * 1000.0
                eng_values[i, EngCh.COP_Y] = mxd / fz * 1000.0
            else:
                eng_values[i, EngCh.COP_X] = 0.0
                eng_values[i, EngCh.COP_Y] = 0.0

        return eng_values


# チャンネル名と単位の定義
CHANNEL_NAMES = {
    EngCh.FX: "Fx", EngCh.FY: "Fy", EngCh.FZ: "Fz",
    EngCh.MX: "Mx", EngCh.MY: "My", EngCh.MZ: "Mz",
    EngCh.MXD: "Mx'", EngCh.MYD: "My'",
    EngCh.COP_X: "COPx", EngCh.COP_Y: "COPy",
}

CHANNEL_UNITS = {
    EngCh.FX: "N", EngCh.FY: "N", EngCh.FZ: "N",
    EngCh.MX: "N*m", EngCh.MY: "N*m", EngCh.MZ: "N*m",
    EngCh.MXD: "N*m", EngCh.MYD: "N*m",
    EngCh.COP_X: "mm", EngCh.COP_Y: "mm",
}


def get_matome_for_frequency(frequency: Frequency) -> int:
    """
    周波数に対応するまとめ数を取得

    Args:
        frequency: 測定周波数

    Returns:
        int: まとめ数
    """
    if frequency == Frequency.F240:
        return 24
    elif frequency == Frequency.F120:
        return 12
    else:
        return 100
