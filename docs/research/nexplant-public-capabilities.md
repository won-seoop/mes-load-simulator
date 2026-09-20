# Samsung SDS Nexplant MES 공개 기능 조사

## 조사 원칙

- 삼성SDS 공식 홈페이지, 공식 제품 소개서, 공식 고객사례만 1차 근거로 사용한다.
- 공개된 문제 영역과 이 프로젝트의 구현 기술을 구분한다.
- 삼성SDS가 공개하지 않은 내부 데이터 모델, 알고리즘, 메시지 브로커를 추측하지 않는다.

## 공식 자료

1. [Nexplant MES 공식 페이지](https://www.samsungsds.com/en/mes/nexplant-mes.html)
2. [Nexplant MES 공식 소개서](https://image.samsungsds.com/en/resources/__icsFiles/afieldfile/2016/12/09/%28Leaflet%29_Nexplant_MES_Eng.pdf)
3. [Nexplant MES 공식 제품 발표자료](https://image.samsungsds.com/us/resources/__icsFiles/afieldfile/2017/01/18/Nexplant_MES_PT_Eng.pdf)
4. [국내 자동차 부품 제조사 스마트공장 구축 사례](https://www.samsungsds.com/kr/case-study/smart-factory-automobile.html)

## 공개 기능과 프로젝트 재현 범위

| 공개 영역 | 공식 자료에서 확인한 문제 | 이 프로젝트에서 재현할 범위 | 공개되지 않아 주장하지 않을 내용 |
|---|---|---|---|
| Scheduling & Dispatching | 생산계획, 공정·설비별 작업순서, 실시간 우선순위와 설비 이벤트 기반 배정 | FIFO, 최소가동시간, 우선순위, 납기 기반 규칙 비교 | 실제 Nexplant 내부 최적화 알고리즘 |
| Manufacturing Operation | 공정·자원 관리, 실시간 데이터 수집, WIP, Tracking/Traceability, 품질 | Work Order, Lot 상태기계, 공정이력, 품질이력, KPI | 실제 Nexplant DB Schema와 Workflow Engine 구현 |
| Equipment Engineering | Sensor/Event/Log/Alarm 수집·처리·분석, 설비 효율과 품질 개선 | 설비 상태·알람·측정 Event Simulator와 이상 시나리오 | 실제 FDC/RMS/EPT/SPC 내부 알고리즘 |
| Machine Control | 표준 프로토콜 기반 설비 데이터 수집과 원격 제어, MES/엔지니어링 연계 | SECS/GEM 개념을 참고한 가상 설비 Adapter와 Interlock | 실제 Fab 설비에 연결했다는 주장 |
| Material Control | Carrier/물류설비 상태와 이송명령, 최적 경로와 이동시간 단축 | Carrier, Buffer, Transport Order 시뮬레이션 | 실제 OHT/AGV 제어 |
| Manufacturing Visibility | 생산·품질·설비·물류 현황과 KPI, Lot 계통도 | WIP, Lot Trace, 설비상태, 품질, OEE Dashboard | 실제 고객사 운영 데이터 |

## 공식 Architecture에서 확인한 연결

```text
Scheduling & Dispatching
    ↕ Best Lot / Work Order
Manufacturing Operation
    ↕ Lot In Progress / Machine Status
Machine Control

Manufacturing Operation
    ↕ Machine Interlock
Equipment Engineering

Manufacturing Operation
    ↕ Lot Transfer
Material Control
```

이 연결은 프로젝트의 도메인 경계를 정하는 근거로만 사용한다. 특정 제품 내부 통신 기술을 의미하지
않는다.

## 프로젝트 기술 선택과의 구분

다음은 삼성SDS 공개 사실이 아니라 이 프로젝트의 자체 선택 후보다.

- FastAPI / SQLAlchemy / PostgreSQL
- Transactional Outbox
- Kafka / RabbitMQ / Redis Streams
- Prometheus / Grafana
- Docker / Kubernetes

이 기술들은 먼저 문제가 재현되고 선택 기준이 생긴 뒤 실험으로 도입한다.

