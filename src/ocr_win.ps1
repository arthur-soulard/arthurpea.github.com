# ocr_win.ps1 — OCR via le moteur integre a Windows (Windows.Media.Ocr).
#
# Aucune dependance externe, aucun binaire a embarquer, aucun acces reseau :
# le moteur fait partie de Windows 10/11 et tourne hors ligne.
#
# Appele par sante.py :
#   powershell -NoProfile -ExecutionPolicy Bypass -File ocr_win.ps1
#              -ImagePath <png> -JsonPath <json>
#
# Ecrit un JSON UTF-8 (sans BOM) : {ok, lang, width, height, words:[{t,x,y,w,h}]}
# Les positions sont indispensables : c'est elles qui permettent d'apparier
# un libelle a sa valeur sur la meme ligne, l'ordre de lecture du moteur
# n'etant pas fiable sur une mise en page en colonnes.

param(
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [Parameter(Mandatory = $true)][string]$JsonPath
)

$ErrorActionPreference = "Stop"

function Write-Json($obj) {
    $json = $obj | ConvertTo-Json -Depth 4 -Compress
    [System.IO.File]::WriteAllText($JsonPath, $json, (New-Object System.Text.UTF8Encoding $false))
}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    # Passerelle IAsyncOperation -> Task, necessaire pour attendre les API WinRT
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

    function Await($task, $resultType) {
        $netTask = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($task))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }

    [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

    $file    = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $stream  = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap  = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    # Langue du profil utilisateur ; repli sur le francais puis l'anglais.
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        foreach ($tag in @("fr-FR", "en-US")) {
            try {
                $lang = New-Object Windows.Globalization.Language $tag
                $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
                if ($null -ne $engine) { break }
            } catch { }
        }
    }
    if ($null -eq $engine) {
        Write-Json ([pscustomobject]@{ ok = $false; error = "no_engine" })
        exit 0
    }

    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $words = foreach ($line in $result.Lines) {
        foreach ($word in $line.Words) {
            [pscustomobject]@{
                t = $word.Text
                x = [int]$word.BoundingRect.X
                y = [int]$word.BoundingRect.Y
                w = [int]$word.BoundingRect.Width
                h = [int]$word.BoundingRect.Height
            }
        }
    }

    Write-Json ([pscustomobject]@{
        ok     = $true
        lang   = $engine.RecognizerLanguage.LanguageTag
        width  = $bitmap.PixelWidth
        height = $bitmap.PixelHeight
        words  = @($words)
    })
}
catch {
    Write-Json ([pscustomobject]@{ ok = $false; error = $_.Exception.Message })
}
