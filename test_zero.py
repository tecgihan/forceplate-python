"""
ゼロ調整テスト

フォースプレートに接続してゼロ調整を実行する
"""

from forceplate import ForcePlate, RmtStatus


def main():
    print("=" * 60)
    print("フォースプレート ゼロ調整テスト")
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
    print(f"  ステータス: {fp.status.name}")

    # ゼロ調整前の確認
    if fp.status != RmtStatus.IDLE:
        print(f"\n  ゼロ調整はIdle状態でのみ可能です（現在: {fp.status.name}）")
        fp.disconnect()
        return

    # ゼロ調整実行
    print("\n[ゼロ調整]")
    print("  ゼロ調整中... (フォースプレートに荷重をかけないでください)")

    if fp.zero():
        print("  ゼロ調整完了")
    else:
        print("  ゼロ調整失敗")

    print(f"  現在のステータス: {fp.status.name}")

    # 切断
    print("\n[切断処理]")
    fp.disconnect()
    print("  切断完了")

    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
