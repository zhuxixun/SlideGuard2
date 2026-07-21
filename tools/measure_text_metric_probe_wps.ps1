param(
    [Parameter(Mandatory = $true)]
    [string]$PptxPath,

    [Parameter(Mandatory = $true)]
    [string]$CsvPath
)

$resolvedPptx = (Resolve-Path -LiteralPath $PptxPath).Path
$resolvedCsv = (Resolve-Path -LiteralPath $CsvPath).Path
$rows = @(Import-Csv -LiteralPath $resolvedCsv)
$app = $null
$presentation = $null

try {
    $app = New-Object -ComObject KWPP.Application
    # WPS rejects a fully hidden COM instance. Open without a document window.
    $app.Visible = 1
    $presentation = $app.Presentations.Open($resolvedPptx, $true, $false, $false)
    if ($presentation.Slides.Count -ne $rows.Count) {
        throw "PPTX slide count does not match CSV row count"
    }

    for ($index = 1; $index -le $presentation.Slides.Count; $index++) {
        $slide = $presentation.Slides.Item($index)
        if ($slide.Shapes.Count -lt 2) {
            throw "Slide ${index} does not contain the metric text box"
        }
        $shape = $slide.Shapes.Item(2)
        $boundWidth = [double]$shape.TextFrame.TextRange.BoundWidth
        $pillowWidth = [double]$rows[$index - 1].pillow_width_pt
        $absoluteError = [Math]::Abs($boundWidth - $pillowWidth)
        $rows[$index - 1].wps_bound_width_pt = $boundWidth.ToString("0.###")
        $rows[$index - 1].wps_absolute_error_pt = $absoluteError.ToString("0.###")
        $rows[$index - 1].wps_result = if ($absoluteError -le 2) { "pass" } else { "fail" }
    }

    $rows | Export-Csv -LiteralPath $resolvedCsv -NoTypeInformation -Encoding utf8
}
finally {
    if ($presentation -ne $null) {
        $presentation.Close()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) | Out-Null
    }
    if ($app -ne $null) {
        $app.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
    }
}
