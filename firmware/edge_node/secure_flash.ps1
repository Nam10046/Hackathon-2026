# Flash the edge node to an ESP32-C6 that has Secure Boot V2 + flash encryption (development mode) burned in.
#   ROM checks the bootloader signature  -> we sign bootloader.bin (and the app) with YOUR key
#   flash is encrypted with a key inside the chip -> esptool --encrypt lets the chip encrypt the data itself
# A normal PlatformIO upload (unsigned, plain) makes such a board stop booting. Use this instead.
#
# Usage (key stays OUTSIDE the repo, never commit it):
#   $env:SB_KEY = "C:\Users\Nam\esp_keys\secure_boot_signing_key.pem"
#   .\secure_flash.ps1                 # build + sign + flash
#   .\secure_flash.ps1 -NoBuild        # sign + flash the last build (used by the PlatformIO Upload button)
param(
  [string]$Key = $env:SB_KEY,
  [string]$Port = "COM4",
  [string]$Env = "esp32c6_secure",
  [string]$ExpectedDigest = "08dde9c588b3f206653d234898b8b059652469f7ed226fe55f5de21e72b8ffff",  # eFuse BLOCK_KEY0 of this board
  [switch]$NoBuild
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $Key -or -not (Test-Path $Key)) {
  throw "Signing key not found. Run:  `$env:SB_KEY = 'C:\path\to\secure_boot_signing_key.pem'   (keep it outside the repo)"
}
if ((Resolve-Path $Key).Path.StartsWith((Resolve-Path "$PSScriptRoot\..\..").Path)) {
  throw "The key is inside the repo folder. Move it outside (e.g. C:\Users\<you>\esp_keys\) so it can never be committed."
}

# esptool in its own venv (PlatformIO's penv has an incompatible bitstring)
$py = "$env:TEMP\efv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  & "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" -m venv "$env:TEMP\efv"
  & $py -m pip install -q esptool "bitstring<5"
}
function Run { & $py @args; if ($LASTEXITCODE) { throw "failed: $args" } }

if (-not $NoBuild) {
  & "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -e $Env
  if ($LASTEXITCODE) { throw "build failed" }
}
$b = ".pio\build\$Env"
$out = "$b\secure"
New-Item -ItemType Directory -Force $out | Out-Null

# 1) safety: the key must be the one whose digest is burned in the chip
Run -m espsecure digest-sbv2-public-key --keyfile $Key -o "$out\digest.bin"
$hex = ([BitConverter]::ToString([IO.File]::ReadAllBytes("$out\digest.bin"))).Replace("-", "").ToLower()
if ($hex -ne $ExpectedDigest) { throw "Key does NOT match this chip (digest $hex). Stopping - nothing was flashed." }
Write-Host "Key matches the chip's Secure Boot digest." -ForegroundColor Green

# 2) sign bootloader + app (Secure Boot V2, RSA-3072)
Run -m espsecure sign-data --version 2 --keyfile $Key -o "$out\bootloader-signed.bin" "$b\bootloader.bin"
Run -m espsecure sign-data --version 2 --keyfile $Key -o "$out\firmware-signed.bin" "$b\firmware.bin"
Run -m espsecure verify-signature --version 2 --keyfile $Key "$out\bootloader-signed.bin"
$bl = (Get-Item "$out\bootloader-signed.bin").Length
if ($bl -gt 0x8000) { throw "Signed bootloader is $bl bytes - does not fit before the partition table at 0x8000." }

# 3) flash, encrypted by the chip (development-mode flash encryption allows this)
$app0 = "$env:USERPROFILE\.platformio\packages\framework-arduinoespressif32\tools\partitions\boot_app0.bin"
# blank the NVS area (old settings/Wi-Fi data). esptool refuses "erase" on a secured chip, but a plain write of 0xFF
# (= erased flash) is allowed. NVS is not an encrypted partition, so this one is written WITHOUT --encrypt.
[IO.File]::WriteAllBytes("$PWD\$out\nvs_blank.bin", [byte[]](,0xFF * 0x5000))
Run -m esptool --chip esp32c6 -p $Port -b 460800 --before default-reset --after no-reset write-flash 0x9000 "$out\nvs_blank.bin"
Run -m esptool --chip esp32c6 -p $Port -b 460800 --before default-reset --after hard-reset write-flash --encrypt `
  0x0 "$out\bootloader-signed.bin" 0x8000 "$b\partitions.bin" 0xe000 $app0 0x10000 "$out\firmware-signed.bin"
Write-Host "Done. Open the monitor:  pio device monitor -e $Env" -ForegroundColor Green
