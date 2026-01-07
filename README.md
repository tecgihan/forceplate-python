# フォースプレート Python Library

テック技販製フォースプレート用のPythonライブラリです。

## 機能

- FTDI USB経由でのデバイス接続・通信
- 測定データの収集（120Hz〜10000Hz）
- ゼロ調整
- AD値から工学値への変換
  - 6分力（Fx, Fy, Fz, Mx, My, Mz）
  - 作用面上モーメント（Mx', My'）
  - COP（Center of Pressure）

## 必要条件

- Python 3.8以上
- FTDI D2XXドライバ（FTDIの公式サイトからダウンロード）

## インストール

### Windows

1. FTDI D2XXドライバをインストール
   - https://ftdichip.com/drivers/d2xx-drivers/
   - または、デバイス接続時に自動インストールされます

2. Pythonパッケージのインストール
   ```
   pip install -r requirements.txt
   ```

### Linux (Ubuntu/Debian)

1. FTDI D2XXライブラリをインストール
   ```bash
   # ダウンロード（バージョンは最新を確認: https://ftdichip.com/drivers/d2xx-drivers/）
   wget https://ftdichip.com/wp-content/uploads/2025/11/libftd2xx-linux-x86_64-1.4.34.tgz

   # 展開
   tar xzf libftd2xx-linux-x86_64-1.4.34.tgz

   # インストール
   cd linux-x86_64
   sudo cp libftd2xx.so /usr/local/lib/libftd2xx.so.1.4.34
   sudo ln -sf /usr/local/lib/libftd2xx.so.1.4.34 /usr/local/lib/libftd2xx.so
   sudo chmod 0755 /usr/local/lib/libftd2xx.so.1.4.34
   sudo ldconfig
   ```

2. Pythonパッケージのインストール
   ```bash
   pip install -r requirements.txt
   ```

3. ftdi_sioモジュールのアンロード（実行時に必要）

   Linuxのftdi_sioカーネルモジュールがデバイスを先に確保するため、D2XXライブラリからアクセスできません。
   デバイス使用前に以下を実行してください：
   ```bash
   sudo rmmod ftdi_sio
   sudo rmmod usbserial
   ```

4. udevルールの設定（sudoなしで実行する場合）

   デフォルトではUSBデバイスへのアクセスにroot権限が必要です。
   以下のudevルールを追加すると、一般ユーザーでも実行できます：
   ```bash
   # udevルールを作成
   sudo tee /etc/udev/rules.d/99-ftdi.rules << 'EOF'
   # FTDI FT232 - allow all users
   SUBSYSTEM=="usb", ATTR{idVendor}=="0403", ATTR{idProduct}=="6001", MODE="0666"
   EOF

   # ルールを再読み込み
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```
   設定後、USBデバイスを再接続してください。

### WSL2 (Windows Subsystem for Linux)

WSL2でUSBデバイスを使用するには、usbipd-winが必要です。

1. Windows側でusbipd-winをインストール
   ```powershell
   winget install usbipd
   ```

2. USBデバイスをWSLにアタッチ（PowerShell管理者）
   ```powershell
   usbipd list                        # BUSIDを確認
   usbipd bind --busid <BUSID>        # 初回のみ
   usbipd attach --wsl --busid <BUSID>
   ```

3. WSL側でftdi_sioをアンロード
   ```bash
   sudo rmmod ftdi_sio
   sudo rmmod usbserial
   ```

## ファイル構成

| ファイル | 説明 |
|----------|------|
| `forceplate.py` | メインデバイス制御クラス |
| `ftdi_comm.py` | FTDI USB通信モジュール |
| `packet_parser.py` | パケット解析・工学値変換 |
| `test_connect.py` | 接続テスト |
| `test_zero.py` | ゼロ調整テスト |
| `test_measure.py` | 測定テスト（リアルタイム表示） |
| `test_measure_nozero.py` | 測定テスト（ゼロ調整なし） |
| `test_ext.py` | 外部トリガ測定テスト |

## 使い方

### 接続テスト

```python
from forceplate import ForcePlate

fp = ForcePlate()

# デバイス一覧を取得
devices = fp.list_devices()
for dev in devices:
    print(f"Index: {dev['index']}, Serial: {dev['serial']}")

# 接続
if fp.connect(0):
    print(f"接続成功: Serial={fp.rmt_info.serial}")
    fp.disconnect()
```

### 測定

```python
import time
from forceplate import ForcePlate, Frequency, Range
from packet_parser import EngCh

fp = ForcePlate()

# 接続
if fp.connect(0):
    # 測定設定
    fp.set_frequency(Frequency.F1000)  # 1000Hz
    fp.set_range(Range.R3K)            # 3000Nレンジ

    # ゼロ調整
    fp.zero()

    # 測定開始
    fp.start()

    # データ取得・工学値変換
    while measuring:
        if fp.data_count > 0:
            ad_data = fp.get_data()
            for fp_idx in range(fp.fp_count):
                # az: FP上面～作用点までの距離（敷物の厚み）[mm]
                eng_data = fp.ad_to_eng(ad_data[fp_idx], fp_idx, az=10.0)
                fz = eng_data[0, EngCh.FZ]  # 鉛直力
                cop_x = eng_data[0, EngCh.COP_X]  # COP X
                cop_y = eng_data[0, EngCh.COP_Y]  # COP Y
                # データを処理...
        time.sleep(0.0001)  # GIL競合回避

    # 測定停止
    fp.stop()
    fp.disconnect()
```

## 工学値チャンネル（10ch）

| チャンネル | 説明 | 単位 |
|------------|------|------|
| FX | 水平力X | N |
| FY | 水平力Y | N |
| FZ | 鉛直力 | N |
| MX | モーメントX | N*m |
| MY | モーメントY | N*m |
| MZ | モーメントZ | N*m |
| MXD | 作用面上モーメントX (Mx') | N*m |
| MYD | 作用面上モーメントY (My') | N*m |
| COP_X | 圧力中心X | mm |
| COP_Y | 圧力中心Y | mm |

## 測定周波数

| 周波数 | まとめ数 |
|--------|----------|
| 10000Hz | 100 |
| 5000Hz | 100 |
| 2500Hz | 100 |
| 1000Hz | 100 |
| 500Hz | 100 |
| 250Hz | 100 |
| 240Hz | 24 |
| 120Hz | 12 |

## 測定レンジ

| レンジ | 説明 |
|--------|------|
| R3K | 3000N |
| R6K | 6000N |
| R10K | 10000N |

## COP計算仕様

```
# センサ中心～作用点までの距離
total_az = |az0| * 1000 + az [mm]
  - az0: センサ中心～FP上面 [m]（AmpInfoから取得、絶対値を使用）
  - az: FP上面～作用点までの距離（敷物の厚み）[mm]

# 作用面上のモーメント
Mx' = Mx - Fy * total_az / 1000
My' = My + Fx * total_az / 1000

# COP (Fz >= FzLimit のとき)
COPx = -My' / Fz * 1000 [mm]
COPy = Mx' / Fz * 1000 [mm]
```

## 注意事項

- 設定変更はIdle状態でのみ可能
- ゼロ調整は測定前に毎回実行してください
- **測定ループには `time.sleep(0.0001)` を入れてください**（GIL競合回避のため）

## APIリファレンス

### プロパティ

| プロパティ | 型 | 説明 |
|------------|-----|------|
| `status` | `RmtStatus` | リモコンのステータス |
| `rmt_info` | `RmtInfo` | リモコン情報 |
| `fp_count` | `int` | 接続FP台数 |
| `frequency` | `Frequency` | サンプリング周波数 |
| `range` | `Range` | 測定レンジ |
| `matome` | `int` | まとめ数 |
| `data_count` | `int` | バッファ内のデータ数 |
| `is_connected` | `bool` | 接続状態 |

### RmtStatus

| 値 | 説明 |
|----|------|
| `NO_DEVICE` | 未接続 |
| `IDLE` | 待機中 |
| `EXT` | 外部トリガ待ち受け中 |
| `MEASURE` | 測定中 |
| `ZERO` | ゼロ調整中 |
| `LEVEL` | レベルトリガ待受中 |
| `SLEEP` | スリープ中 |
| `ERROR` | エラー発生 |

### 接続・切断

| メソッド | 引数 | 戻り値 | 説明 |
|----------|------|--------|------|
| `list_devices()` | なし | `List[dict]` | 接続可能なデバイス一覧を取得 |
| `connect(device_index)` | `int` | `bool` | インデックスで接続 |
| `disconnect()` | なし | なし | 切断 |

### 測定制御

| メソッド | 引数 | 戻り値 | 説明 |
|----------|------|--------|------|
| `start()` | なし | `bool` | 測定開始 |
| `stop()` | なし | `bool` | 測定停止 |
| `ext()` | なし | `bool` | 外部トリガ待ち状態に移行 |
| `zero()` | なし | `bool` | ゼロ調整（10秒タイムアウト） |

### データ取得・変換

| メソッド | 引数 | 戻り値 | 説明 |
|----------|------|--------|------|
| `get_data()` | なし | `np.ndarray` | AD値配列を取得 |
| `ad_to_eng(ad_values, fp_index, az, fz_limit)` | 各種 | `np.ndarray` | AD値を工学値に変換 |

### 設定

| メソッド | 引数 | 戻り値 | 説明 |
|----------|------|--------|------|
| `set_frequency(frequency)` | `Frequency` | `bool` | サンプリング周波数設定 |
| `set_range(range_val)` | `Range` | `bool` | 測定レンジ設定 |
| `amp(index)` | `int` | `AmpInfo` | アンプ情報取得 |

## ライセンス

MIT License - 株式会社テック技販

## バージョン

- 1.0.0.0: 初版リリース
