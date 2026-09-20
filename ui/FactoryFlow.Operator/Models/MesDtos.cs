using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace FactoryFlow.Operator.Models;

public sealed class EquipmentDto
{
    public int Id { get; init; }
    public string Name { get; init; } = "";
    [JsonPropertyName("process_step")] public string ProcessStep { get; init; } = "";
    public string Status { get; init; } = "";
    [JsonPropertyName("run_seconds")] public double RunSeconds { get; init; }
    [JsonPropertyName("dispatch_count")] public int DispatchCount { get; init; }
}

public sealed class LotDto
{
    public int Id { get; init; }
    public string Product { get; init; } = "";
    public int Quantity { get; init; }
    [JsonPropertyName("step_index")] public int StepIndex { get; init; }
    public string Status { get; init; } = "";
}

public sealed class WorkOrderDto
{
    public int Id { get; init; }
    [JsonPropertyName("order_no")] public string OrderNo { get; init; } = "";
    [JsonPropertyName("product_code")] public string ProductCode { get; init; } = "";
    [JsonPropertyName("planned_quantity")] public int PlannedQuantity { get; init; }
    [JsonPropertyName("released_quantity")] public int ReleasedQuantity { get; init; }
    [JsonPropertyName("completed_quantity")] public int CompletedQuantity { get; init; }
    public int Priority { get; init; }
    public string Status { get; init; } = "";
}

public sealed class MesMetricsDto
{
    [JsonPropertyName("wip_count")] public int WipCount { get; init; }
    [JsonPropertyName("completed_today")] public int CompletedToday { get; init; }
    [JsonPropertyName("scrap_count")] public int ScrapCount { get; init; }
    [JsonPropertyName("yield_rate")] public double YieldRate { get; init; }
    [JsonPropertyName("avg_cycle_time_seconds")] public double? AverageCycleTimeSeconds { get; init; }
    [JsonPropertyName("throughput_per_hour")] public double ThroughputPerHour { get; init; }
}

public sealed class QualityMetricsDto
{
    [JsonPropertyName("total_inspections")] public int TotalInspections { get; init; }
    [JsonPropertyName("pass_count")] public int PassCount { get; init; }
    [JsonPropertyName("fail_count")] public int FailCount { get; init; }
    [JsonPropertyName("defect_rate")] public double DefectRate { get; init; }
    [JsonPropertyName("first_pass_yield")] public double FirstPassYield { get; init; }
    [JsonPropertyName("scrap_count")] public int ScrapCount { get; init; }
    [JsonPropertyName("rework_count")] public int ReworkCount { get; init; }
    [JsonPropertyName("defects_by_equipment")] public Dictionary<string, int> DefectsByEquipment { get; init; } = [];
}

public sealed class QualityAnomalyReportDto
{
    public string Method { get; init; } = "";
    [JsonPropertyName("anomalies")] public List<EquipmentQualityAnomalyDto> Anomalies { get; init; } = [];
}

public sealed class EquipmentQualityAnomalyDto
{
    [JsonPropertyName("equipment_name")] public string EquipmentName { get; init; } = "";
    [JsonPropertyName("fail_count")] public int FailCount { get; init; }
    [JsonPropertyName("defect_rate")] public double DefectRate { get; init; }
    [JsonPropertyName("peer_mean_rate")] public double PeerMeanRate { get; init; }
    [JsonPropertyName("rate_delta")] public double RateDelta { get; init; }
    public string Severity { get; init; } = "";
}

public sealed record EquipmentRow(
    string Name,
    string ProcessStep,
    string Status,
    string StatusColor,
    string RunTime,
    string Dispatches);

public sealed record StageRow(string Name, int Count, string Accent);

public sealed record WorkOrderRow(
    string OrderNo,
    string Product,
    string Status,
    string Progress,
    string Priority);

public sealed record DefectRow(string Equipment, int Count, string Severity, string Color);
