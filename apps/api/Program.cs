using Microsoft.Extensions.Diagnostics.HealthChecks;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);

var connectionString = builder.Configuration.GetConnectionString("Database");
if (string.IsNullOrWhiteSpace(connectionString))
    throw new InvalidOperationException("Set ConnectionStrings__Database before starting Findie API.");

try
{
    _ = new NpgsqlConnectionStringBuilder(connectionString);
}
catch (ArgumentException)
{
    throw new InvalidOperationException("ConnectionStrings__Database is invalid.");
}

if (!Uri.TryCreate(builder.Configuration["Ai:BaseUrl"], UriKind.Absolute, out var aiBaseUrl)
    || (aiBaseUrl.Scheme != Uri.UriSchemeHttp && aiBaseUrl.Scheme != Uri.UriSchemeHttps)
    || !string.IsNullOrEmpty(aiBaseUrl.UserInfo)
    || !string.IsNullOrEmpty(aiBaseUrl.Query)
    || !string.IsNullOrEmpty(aiBaseUrl.Fragment))
    throw new InvalidOperationException("Ai__BaseUrl must be an absolute HTTP(S) URL without credentials, query or fragment.");

var serviceToken = builder.Configuration["Ai:ServiceToken"];
if (string.IsNullOrWhiteSpace(serviceToken) || serviceToken.Any(char.IsControl))
    throw new InvalidOperationException("Set Ai__ServiceToken to a nonblank service token without control characters.");

if (!int.TryParse(builder.Configuration["Ai:TimeoutSeconds"], out var aiTimeout) || aiTimeout is < 1 or > 120)
    throw new InvalidOperationException("Ai__TimeoutSeconds must be between 1 and 120.");

builder.Services.AddSingleton(_ => NpgsqlDataSource.Create(connectionString));
builder.Services.AddHealthChecks().AddCheck<DatabaseHealthCheck>("database", timeout: TimeSpan.FromSeconds(5));
builder.Services.AddHttpClient("ai", client =>
{
    client.BaseAddress = aiBaseUrl;
    client.Timeout = TimeSpan.FromSeconds(aiTimeout);
    client.DefaultRequestHeaders.Add("X-Service-Token", serviceToken);
}).ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });

var app = builder.Build();

app.MapGet("/health/live", () => Results.Ok(new { status = "ok", stage = "scaffold" }));

app.MapGet("/health/ready", async (HealthCheckService healthChecks, CancellationToken cancellationToken) =>
{
    var report = await healthChecks.CheckHealthAsync(cancellationToken);
    var ready = report.Status == HealthStatus.Healthy;
    return Results.Json(new { status = ready ? "ready" : "not_ready", database = ready ? "ready" : "unavailable" },
        statusCode: ready ? StatusCodes.Status200OK : StatusCodes.Status503ServiceUnavailable);
});

app.MapGet("/api/system/status", async (HealthCheckService healthChecks, IHttpClientFactory clients,
    CancellationToken cancellationToken) =>
{
    var databaseCheck = healthChecks.CheckHealthAsync(cancellationToken);
    var ai = "unavailable";
    try
    {
        using var response = await clients.CreateClient("ai").GetAsync("/health/ready", cancellationToken);
        if (response.IsSuccessStatusCode)
            ai = "ready";
    }
    catch (Exception exception) when (exception is HttpRequestException or OperationCanceledException)
    {
        // Dependency failures remain visible as unavailable; no credentials or remote body leave the API.
    }

    var database = (await databaseCheck).Status == HealthStatus.Healthy ? "ready" : "unavailable";
    return Results.Ok(new
    {
        name = "Findie API",
        stage = "scaffold",
        database,
        ai,
        features = new { business = false, authentication = false, storage = false }
    });
});

app.Run();
