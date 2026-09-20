using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FactoryFlow.Operator.Models;
using FactoryFlow.Operator.Services;

namespace FactoryFlow.Operator.ViewModels;

public partial class MainViewModel : ViewModelBase
{
    private static readonly string[] Route = ["ETCH", "CVD", "CMP", "INSPECT"];
    private readonly MesApiClient _apiClient;

    public ObservableCollection<EquipmentRow> Equipment { get; } = [];
    public ObservableCollection<StageRow> Stages { get; } = [];
    public ObservableCollection<WorkOrderRow> WorkOrders { get; } = [];
    public ObservableCollection<DefectRow> Defects { get; } = [];

    [ObservableProperty] public partial string ConnectionStatus { get; set; } = "CONNECTING";
    [ObservableProperty] public partial string ConnectionColor { get; set; } = "#F5B942";
    [ObservableProperty] public partial string LastUpdated { get; set; } = "-";
    [ObservableProperty] public partial string Wip { get; set; } = "-";
    [ObservableProperty] public partial string Completed { get; set; } = "-";
    [ObservableProperty] public partial string Yield { get; set; } = "-";
    [ObservableProperty] public partial string Throughput { get; set; } = "-";
    [ObservableProperty] public partial string FirstPassYield { get; set; } = "-";
    [ObservableProperty] public partial string DefectRate { get; set; } = "-";
    [ObservableProperty] public partial string QualitySignal { get; set; } = "No quality signal";
    [ObservableProperty] public partial bool IsRefreshing { get; set; }

    public MainViewModel()
    {
        var baseUrl = Environment.GetEnvironmentVariable("MES_API_BASE_URL")
            ?? "http://127.0.0.1:8000";
        _apiClient = new MesApiClient(baseUrl);
        _ = RefreshAsync();
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        if (IsRefreshing) return;
        IsRefreshing = true;
        try
        {
            var equipmentTask = _apiClient.GetEquipmentAsync();
            var lotsTask = _apiClient.GetLotsAsync();
            var workOrdersTask = _apiClient.GetWorkOrdersAsync();
            var metricsTask = _apiClient.GetMetricsAsync();
            var qualityTask = _apiClient.GetQualityMetricsAsync();
            var anomaliesTask = _apiClient.GetQualityAnomaliesAsync();
            await Task.WhenAll(
                equipmentTask,
                lotsTask,
                workOrdersTask,
                metricsTask,
                qualityTask,
                anomaliesTask);

            ApplyEquipment(await equipmentTask ?? []);
            ApplyLots(await lotsTask ?? []);
            ApplyWorkOrders(await workOrdersTask ?? []);
            ApplyMetrics(await metricsTask ?? new MesMetricsDto());
            ApplyQuality(
                await qualityTask ?? new QualityMetricsDto(),
                await anomaliesTask ?? new QualityAnomalyReportDto());
            ConnectionStatus = "LIVE";
            ConnectionColor = "#33D17A";
            LastUpdated = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
        }
        catch (Exception)
        {
            ConnectionStatus = "API OFFLINE";
            ConnectionColor = "#FF6B6B";
            QualitySignal = "Start FastAPI on :8000, then refresh";
        }
        finally
        {
            IsRefreshing = false;
        }
    }

    private void ApplyEquipment(IEnumerable<EquipmentDto> rows)
    {
        Equipment.Clear();
        foreach (var item in rows.OrderBy(x => x.ProcessStep).ThenBy(x => x.Name))
        {
            var color = item.Status switch
            {
                "RUN" => "#33D17A",
                "DOWN" => "#FF6B6B",
                _ => "#8B95A7",
            };
            Equipment.Add(new EquipmentRow(
                item.Name,
                item.ProcessStep,
                item.Status,
                color,
                $"{item.RunSeconds:N1}s",
                item.DispatchCount.ToString("N0")));
        }
    }

    private void ApplyLots(IReadOnlyCollection<LotDto> lots)
    {
        Stages.Clear();
        string[] accents = ["#6EA8FE", "#9B8AFB", "#F5B942", "#36C5B3"];
        for (var index = 0; index < Route.Length; index++)
        {
            var step = index;
            var count = lots.Count(lot =>
                (lot.Status is "WAITING" or "PROCESSING" or "HOLD")
                && lot.StepIndex == step);
            Stages.Add(new StageRow(Route[index], count, accents[index]));
        }
        Stages.Add(new StageRow("QUALITY HOLD", lots.Count(x => x.Status == "QUALITY_HOLD"), "#FF8A65"));
        Stages.Add(new StageRow("REWORK", lots.Count(x => x.Status == "REWORK"), "#EC7CC3"));
    }

    private void ApplyWorkOrders(IEnumerable<WorkOrderDto> rows)
    {
        WorkOrders.Clear();
        foreach (var item in rows.Take(8))
        {
            WorkOrders.Add(new WorkOrderRow(
                item.OrderNo,
                item.ProductCode,
                item.Status,
                $"{item.CompletedQuantity:N0} / {item.PlannedQuantity:N0}",
                $"P{item.Priority}"));
        }
    }

    private void ApplyMetrics(MesMetricsDto metrics)
    {
        Wip = metrics.WipCount.ToString("N0");
        Completed = metrics.CompletedToday.ToString("N0");
        Yield = metrics.YieldRate.ToString("P1");
        Throughput = $"{metrics.ThroughputPerHour:N1}/h";
    }

    private void ApplyQuality(
        QualityMetricsDto quality,
        QualityAnomalyReportDto anomalyReport)
    {
        FirstPassYield = quality.FirstPassYield.ToString("P1");
        DefectRate = quality.DefectRate.ToString("P1");
        Defects.Clear();
        var anomalies = anomalyReport.Anomalies.ToDictionary(x => x.EquipmentName);
        foreach (var pair in quality.DefectsByEquipment.OrderByDescending(x => x.Value))
        {
            var severity = anomalies.TryGetValue(pair.Key, out var anomaly)
                ? anomaly.Severity
                : "OBSERVED";
            var color = severity == "CRITICAL" ? "#FF6B6B" : severity == "WARNING" ? "#F5B942" : "#6EA8FE";
            Defects.Add(new DefectRow(pair.Key, pair.Value, severity, color));
        }
        QualitySignal = anomalyReport.Anomalies.Count == 0
            ? "No peer-rate anomaly passed the statistical guard"
            : $"{anomalyReport.Anomalies[0].EquipmentName}: "
              + $"{anomalyReport.Anomalies[0].DefectRate:P1} defects vs "
              + $"{anomalyReport.Anomalies[0].PeerMeanRate:P1} peer mean";
    }
}
