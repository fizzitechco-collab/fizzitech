# Opens the local dashboard once the server is accepting connections.
# Exits silently if the server never starts. No remote traffic.
$url = 'http://127.0.0.1:8765'
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $url -Method GET -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Start-Process $url
            break
        }
    } catch { }
    Start-Sleep -Seconds 2
}
