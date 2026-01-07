"""
接続テスト

フォースプレートに接続してデバイス情報を表示する
"""

from forceplate import ForcePlate


def main():
    print("=" * 60)
    print("フォースプレート 接続テスト")
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

    # リモコン情報表示
    print("\n[リモコン情報]")
    print(f"  シリアル番号: {fp.rmt_info.serial}")
    print(f"  バージョン: {fp.rmt_info.version}")
    print(f"  ステータス: {fp.status.name}")

    # 設定情報表示
    print("\n[測定設定]")
    print(f"  測定周波数: {fp.frequency.value} Hz")
    print(f"  測定レンジ: {fp.range.name}")
    print(f"  まとめ数: {fp.matome}")

    # FP情報表示
    print(f"\n[フォースプレート情報] (接続台数: {fp.fp_count})")
    for i in range(fp.fp_count):
        amp = fp.amp(i)
        if amp:
            print(f"\n  FP {i + 1}:")
            print(f"    シリアル番号: {amp.serial}")
            print(f"    バージョン: {amp.version}")
            print(f"    az0（センサ中心～FP上面）: {amp.az0} m ({amp.az0 * 1000} mm)")
            print(f"    フルスケール (R3K):  Fx={amp.fs[0,0]:6.0f}, Fy={amp.fs[0,1]:6.0f}, Fz={amp.fs[0,2]:6.0f}, " +
                  f"Mx={amp.fs[0,3]:6.0f}, My={amp.fs[0,4]:6.0f}, Mz={amp.fs[0,5]:6.0f}")
            print(f"    フルスケール (R6K):  Fx={amp.fs[1,0]:6.0f}, Fy={amp.fs[1,1]:6.0f}, Fz={amp.fs[1,2]:6.0f}, " +
                  f"Mx={amp.fs[1,3]:6.0f}, My={amp.fs[1,4]:6.0f}, Mz={amp.fs[1,5]:6.0f}")
            print(f"    フルスケール (R10K): Fx={amp.fs[2,0]:6.0f}, Fy={amp.fs[2,1]:6.0f}, Fz={amp.fs[2,2]:6.0f}, " +
                  f"Mx={amp.fs[2,3]:6.0f}, My={amp.fs[2,4]:6.0f}, Mz={amp.fs[2,5]:6.0f}")

    # 切断
    print("\n[切断処理]")
    fp.disconnect()
    print("  切断完了")

    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
