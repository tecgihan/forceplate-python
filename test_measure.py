"""
測定テスト

フォースプレートに接続して測定データをリアルタイム表示する
"""

import time
import sys
from forceplate import ForcePlate, RmtStatus, Frequency, Range
from packet_parser import EngCh


def main():
    print("=" * 60)
    print("フォースプレート 測定テスト")
    print("=" * 60)

    fp = ForcePlate()

    # デバイスリスト表示
    print("\n[接続可能なデバイス一覧]")
    devices = fp.list_devices()

    if not devices:
        print("  デバイスが見つかりません")
        return

    for dev in devices:
        print(f"  [{dev['index']}] {dev['description']} (Serial: {dev['serial']})")

    # 最初のデバイスに接続
    print("\n[接続処理]")
    if not fp.connect(0):
        print("  接続失敗")
        return

    print("  接続成功")
    print(f"  シリアル番号: {fp.rmt_info.serial}")
    print(f"  FP台数: {fp.fp_count}")

    # 測定設定
    print("\n[測定設定]")

    # 周波数設定（1000Hz）
    if fp.set_frequency(Frequency.F1000):
        print(f"  周波数: {fp.frequency.value} Hz")
    else:
        print("  周波数設定失敗")

    # レンジ設定（6000N）
    if fp.set_range(Range.R6K):
        print(f"  レンジ: {fp.range.name}")
    else:
        print("  レンジ設定失敗")

    print(f"  まとめ数: {fp.matome}")

    # ゼロ調整
    print("\n[ゼロ調整]")
    print("  ゼロ調整中... (フォースプレートに荷重をかけないでください)")
    if fp.zero():
        print("  ゼロ調整完了")
    else:
        print("  ゼロ調整失敗")
        fp.disconnect()
        return

    # 測定開始
    print("\n[測定開始]")
    print("  Ctrl+C で停止")
    print("-" * 60)

    if not fp.start():
        print("  測定開始失敗")
        fp.disconnect()
        return

    # ヘッダー表示
    print("  FP  |    Fx    |    Fy    |    Fz    |    Mx    |    My    |    Mz    |   COPx   |   COPy   |")
    print("-" * 100)

    try:
        display_interval = 0.1  # 表示間隔（秒）
        last_display_time = time.time()

        while True:
            current_time = time.time()

            # データがあれば処理
            while fp.data_count > 0:
                # AD値取得
                ad_data = fp.get_data()
                if ad_data is None:
                    break

                # 表示間隔チェック
                if current_time - last_display_time >= display_interval:
                    # 各FPのデータを表示
                    for fp_idx in range(fp.fp_count):
                        # 工学値変換（最初のサンプルのみ表示）
                        # az: FP上面～作用点までの距離（敷物の厚み）[mm]
                        eng_data = fp.ad_to_eng(ad_data[fp_idx], fp_idx, az=10.0)
                        fx = eng_data[0, EngCh.FX]
                        fy = eng_data[0, EngCh.FY]
                        fz = eng_data[0, EngCh.FZ]
                        mx = eng_data[0, EngCh.MX]
                        my = eng_data[0, EngCh.MY]
                        mz = eng_data[0, EngCh.MZ]
                        cop_x = eng_data[0, EngCh.COP_X]
                        cop_y = eng_data[0, EngCh.COP_Y]
                        print(f"  {fp_idx+1}   | {fx:8.1f} | {fy:8.1f} | {fz:8.1f} | "
                              f"{mx:8.2f} | {my:8.2f} | {mz:8.2f} | "
                              f"{cop_x:8.1f} | {cop_y:8.1f} |")

                    sys.stdout.flush()
                    last_display_time = current_time

            # GIL競合回避
            time.sleep(0.0001)

    except KeyboardInterrupt:
        print("\n\n[測定停止]")

    # 測定停止
    fp.stop()
    print("  測定停止完了")

    # 切断
    print("\n[切断処理]")
    fp.disconnect()
    print("  切断完了")

    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
