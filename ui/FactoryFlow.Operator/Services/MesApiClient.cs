using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Threading.Tasks;
using FactoryFlow.Operator.Models;

namespace FactoryFlow.Operator.Services;

public sealed class MesApiClient
{
    private readonly HttpClient _httpClient;
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public MesApiClient(string baseUrl)
    {
        _httpClient = new HttpClient
        {
            BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(3),
        };
    }

    public Task<List<EquipmentDto>?> GetEquipmentAsync() =>
        _httpClient.GetFromJsonAsync<List<EquipmentDto>>("equipment", _jsonOptions);

    public Task<List<LotDto>?> GetLotsAsync() =>
        _httpClient.GetFromJsonAsync<List<LotDto>>("lots", _jsonOptions);

    public Task<List<WorkOrderDto>?> GetWorkOrdersAsync() =>
        _httpClient.GetFromJsonAsync<List<WorkOrderDto>>("work-orders", _jsonOptions);

    public Task<MesMetricsDto?> GetMetricsAsync() =>
        _httpClient.GetFromJsonAsync<MesMetricsDto>("metrics", _jsonOptions);

    public Task<QualityMetricsDto?> GetQualityMetricsAsync() =>
        _httpClient.GetFromJsonAsync<QualityMetricsDto>("quality/metrics", _jsonOptions);

    public Task<QualityAnomalyReportDto?> GetQualityAnomaliesAsync() =>
        _httpClient.GetFromJsonAsync<QualityAnomalyReportDto>("quality/anomalies", _jsonOptions);
}
