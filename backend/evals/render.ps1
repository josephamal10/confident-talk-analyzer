# Renders SSML jobs with the built-in Windows voices (System.Speech, no downloads) and records when
# each word starts, which becomes the ground truth for pace and pauses.
# Usage: powershell -ExecutionPolicy Bypass -File render.ps1 <jobs.json>
#   jobs.json: [{"id", "ssml", "voice", "rate", "wav", "events"}]
param([Parameter(Mandatory = $true)][string]$JobsPath)
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @"
using System.Text;
using System.Speech.Synthesis;
using System.Speech.AudioFormat;

public static class EvalVoice {
    // Writes a 16 kHz mono WAV and returns "milliseconds<TAB>word" for every word as it starts.
    public static string Render(string ssml, string wavPath, string voice, int rate) {
        var log = new StringBuilder();
        using (var synth = new SpeechSynthesizer()) {
            synth.SelectVoice(voice);
            synth.Rate = rate;
            synth.SpeakProgress += (sender, e) => log.Append(e.AudioPosition.TotalMilliseconds).Append('\t').Append(e.Text).Append('\n');
            synth.SetOutputToWaveFile(wavPath, new SpeechAudioFormatInfo(16000, AudioBitsPerSample.Sixteen, AudioChannel.Mono));
            synth.SpeakSsml(ssml);
            synth.SetOutputToNull();
        }
        return log.ToString();
    }
}
"@

$voices = @{ "david" = "Microsoft David Desktop"; "zira" = "Microsoft Zira Desktop" }
$jobs = Get-Content -Raw -Encoding UTF8 $JobsPath | ConvertFrom-Json
foreach ($job in $jobs) {
    $events = [EvalVoice]::Render($job.ssml, $job.wav, $voices[$job.voice], [int]$job.rate)
    [System.IO.File]::WriteAllText($job.events, $events, (New-Object System.Text.UTF8Encoding $false))
    Write-Output "rendered $($job.id)"
}
