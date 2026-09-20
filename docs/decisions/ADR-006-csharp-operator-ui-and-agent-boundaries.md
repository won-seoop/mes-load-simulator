# ADR-006: C# Operator UI and MCP/A2A Boundaries

## Status

Accepted — 2026-09-20

## UI Decision

macOS에서 개발·검증하면서 Windows 운영 단말 확장을 보여주기 위해 C# Avalonia XAML + MVVM을
선택한다. WPF는 Windows 전용이고, Web-only UI는 사용자가 원하는 C#/XAML 경험을 만들기 어렵다.

공개 MES/Smart Factory 자료의 WIP, 품질, 설비, 실시간 모니터링 정보구조를 참고하되 특정 회사의
사내 UI 또는 C# 사용을 주장하지 않는다.

## Agent Protocol Decision

- MCP: Agent Host가 MES Resource와 제한된 Tool을 사용하기 위한 연결 계층
- A2A: 독립 Agent 사이의 Task, 상태, Artifact 교환 계층
- Outbox/Broker: 확정 Domain Event를 Consumer로 전달하는 비동기 Event 계층

세 계층을 섞지 않는다. 현재 MCP는 read-only로 시작하며 A2A는 설계 후 Quality Investigation Task부터
도입한다. 설비 제어, Scrap/Rework, Work Order Release는 사람 승인과 Audit가 준비될 때까지 Agent Tool로
노출하지 않는다.
