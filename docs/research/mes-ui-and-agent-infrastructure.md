# MES UI and Agent Infrastructure Research

조사일: 2026-09-20

## 공개 사실과 프로젝트 선택의 경계

### Samsung SDS Nexplant MES 공개 사실

[Samsung SDS 공식 MES 페이지](https://www.samsungsds.com/en/mes/nexplant-mes.html)는 Manufacturing
Operation에서 실시간 데이터 수집, WIP, 실시간 Tracking/Traceability, 검사·불량 관리와 추적을 공개한다.
또한 Workflow Monitoring, 생산·품질 의사결정, Scheduling/Dispatching과 Machine Control 연계를 설명한다.

공개 페이지는 화면의 내부 프레임워크나 현재 UI가 C#으로 작성됐다고 밝히지 않는다. 따라서 이
프로젝트는 “Nexplant가 C# UI를 쓴다”고 주장하지 않는다. 공개된 운영 문제와 정보 구조만 참고한다.

### Hyundai AutoEver 공개 사실

[Hyundai AutoEver Smart Factory 공식 페이지](https://www.hyundai-autoever.com/eng/business-area/digital-transformation/smart-factory/contents.do?cntnSeq=372)는
MES의 계획 작업 실행, Tracking, 생산 상태 분석, 품질 분석, 공정 불량과 수리 이력, 생산설비 상태
모니터링을 공개한다. Intelligent Factory 영역에서는 사용자 중심 시각화, 실시간 통합 모니터링,
Trend와 관리지표/원인별 상세 분석을 설명한다.

같은 페이지의 Smart SCADA는 다음을 공개한다.

- XAML로 작성한 Web Standard Browser SCADA 화면
- gRPC, REST, Kafka 등 Data Interface API
- Windows/Linux, On-premise/VM/Kubernetes 지원
- Cross-browser UX, 과거 Tag Replay, 사용자 Component와 JavaScript Script

이는 Smart SCADA 공개 설명이며 Hyundai AutoEver MES 전체가 C# Desktop UI라는 증거는 아니다.

[Hyundai AutoEver SDF(Factory) 공식 페이지](https://www.hyundai-autoever.com/eng/business-area/digital-transformation/sdf/contents.do?cntnSeq=457)는
Standard MES, Quality Completion, Part Lot Traceability, 3D Monitoring, PHM과 AI Agent를 포함한 확장
방향을 공개한다. 이 프로젝트는 그 내부 구현을 추측하지 않는다.

## FactoryFlow UI에 반영한 운영 패턴

1. 한 화면에서 WIP, 완료, 수율, 처리량, FPY, 불량률을 먼저 본다.
2. 공정별 WIP를 Route 순서로 배치해 병목을 빠르게 찾는다.
3. 설비 상태와 작업 배정 횟수를 같이 표시해 “가동시간이 비슷하다”는 착시를 피한다.
4. 품질 이상 신호에서 장비별 불량 건수만 보여주지 않고 동료 장비 평균과 비교한다.
5. 작업지시는 계획수량/완료수량/상태/우선순위로 Drill-down 한다.
6. LOT Trace, Quality, Anomaly Center를 독립 Navigation으로 확장할 수 있게 한다.

## UI 기술 선택

### 선택: C# + Avalonia XAML + MVVM

- 현재 개발 장비인 Apple Silicon macOS에서 직접 빌드·실행할 수 있다.
- 동일 C#·XAML 코드로 Windows/Linux Desktop까지 확장할 수 있다.
- WPF/XAML 경험과 연결되면서도 Windows 전용 WPF보다 검증 범위가 넓다.
- FastAPI REST를 직접 읽으므로 Backend와 UI의 책임이 분리된다.

[Avalonia 공식 문서](https://docs.avaloniaui.net/docs/get-started)는 C#/XAML과 MVVM Template을
제공하며 Windows, macOS, Linux 배포를 지원한다고 설명한다. 이 기술 선택은 Nexplant 또는 Hyundai
AutoEver의 내부 기술을 재현했다는 의미가 아니라, 공개된 XAML 기반 운영화면 패턴을 이 프로젝트
환경에서 검증하기 위한 자체 선택이다.

## 현재 구현

- `ui/FactoryFlow.Operator`: C# Avalonia Operator Console
- 실제 API: `/equipment`, `/lots`, `/work-orders`, `/metrics`, `/quality/metrics`,
  `/quality/anomalies`
- 화면: Operations KPI, 공정별 WIP, 설비 상태/배정 횟수, 작업지시, 품질 이상 신호
- 환경변수: `MES_API_BASE_URL` (기본 `http://127.0.0.1:8000`)

## 다음 UI 단계

- LOT 검색과 Event Timeline
- Work Order 상세/Release Command는 사용자 확인을 거친 별도 Command 화면
- 설비 Downtime/Alarm History
- 품질 Trend와 Pareto Chart
- 이상 신호 확인(Acknowledge)과 조사 Task 연결
- 장시간 실행, 연결 끊김/재연결, 큰 목록 Virtualization 검증
