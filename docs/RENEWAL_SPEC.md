# 재배대 제어 시스템 리뉴얼 시방서

| 항목 | 내용 |
|---|---|
| 문서 버전 | 1.0 (2026-06-12) |
| 대상 시스템 | CJA Skyfarms 재배대 1/2 제어 시스템 (Raspberry Pi 5) |
| 작성 근거 | 2026-06-11 현행 시스템 전수 분석 + 운영자 답변 25항 |
| 범위 | 재배대 제어 전체 + 카메라/ML 생육 모니터링. 식물 현황 앱(plant-status-app, 포트 8000)은 **범위 제외** |

`[확인필요]` 표시는 코딩 착수 전 운영자 확인 또는 실측이 필요한 항목이다.

---

## 1. 개요 / 목적 / 리뉴얼 배경

### 1.1 목적

Node-RED + Python 혼합 구조를 **Python 단일 스택(제어 데몬 + 웹 UI)** 으로 전면 교체한다.
Node-RED는 완전히 제거하며, 기능 동등성을 유지하되 아래 배경의 구조적 결함을 해소한다.

### 1.2 리뉴얼 배경 (현행 시스템의 확인된 결함)

1. **도징 펌프 OFF 미보장**: 자동 도징의 OFF 명령이 Python stdout → Node-RED JSON 파싱 → GPIO 노드 경로를 거침. 경로상 JSON 파싱 에러가 실제 발생 중(2026-06-11 저널 3건). 수동 도징 OFF는 Node-RED 메모리 타이머뿐이라 크래시 시 펌프 ON 고착.
   운영자 확인 최악 시나리오: 순환펌프 고착 시 양액 고갈 + 배수관 오버플로우, 도징펌프 고착 시 EC 급등/pH 급락으로 식물 전체 괴사.
2. **자원 소유권 분열**: GPIO 핀 16 이중 정의, 시리얼 버스를 프로세스 3개가 /tmp flock으로 공유(락 20초 점유로 센서 폴링 타임아웃 상존), SQLite 다중 writer, 카메라를 pkill로 뺏는 중재.
3. **프로세스 수명 관리 부재**: pythonshell 자식 12개 중 9개만 생존, 죽어도 자동 재시작 없음, 사망 기록 없음.
4. **설정값 하드코딩**: 셋포인트/스케줄/투입량 변경 = 소스 수정. 변경 이력이 "JM edit" 주석뿐.
5. **설정 불일치 잔존**: 자동 도징의 보레이트 115200은 수정 누락 버그(정상값 38400, 운영자 확인). LED2 시간은 코드(07~23시)가 정답(운영자 확인).

### 1.3 리뉴얼 원칙

- 모든 하드웨어(GPIO, 시리얼, 카메라)는 **단일 소유자 프로세스**만 접근한다.
- 도징 펌프 OFF는 어떤 장애 상황에서도 소프트웨어가 보장할 수 있는 최대 수준으로 다중화한다.
- 운영 파라미터(조명 시간, 투입량, 자동 투입 스케줄 등)는 코드 수정 없이 웹 UI에서 변경한다.
- 재시작/정전 복구 시 현재 시각 기준으로 모든 제어 요소가 스케줄에 맞는 상태로 자동 복귀한다(운영자 답변 7, 23).
- 센서 통신 프로토콜·파싱·주기는 현행 코드를 기준으로 이식한다(운영자 답변 9).

---

## 2. 하드웨어 구성 및 인터페이스

### 2.1 플랫폼

| 항목 | 사양 |
|---|---|
| 본체 | Raspberry Pi 5, Debian 12 (bookworm), Python 3.11 |
| 스토리지 | microSD 29GB (현행 유지) |
| RTC | 없음. 부팅 시 시간 동기화 완료 전 제어 시작 금지 (4.3절) |
| 카메라 | Logitech C270 (USB, `/dev/v4l/by-id/usb-046d_C270_HD_WEBCAM_200901010001-video-index0`). 교체/추가 없음(운영자 답변 14) |

### 2.2 GPIO 핀맵 (BCM, 전 핀 active-low 릴레이: 출력 0=ON, 1=OFF)

리뉴얼 후 모든 핀은 제어 데몬 단독 소유. 확장 계획 없음, 아래 핀만 사용(운영자 답변 3).

| BCM | 장치 | 분류 | 비고 |
|---|---|---|---|
| 4 | 재배대1 LED | 조명 | |
| 5 | 재배대1 순환펌프 | 순환 | |
| 6, 12 | 재배대2 순환펌프 | 순환 | 두 핀 동시 구동 |
| 13 | 미니팬 | 환기 | |
| 16 | 공기순환기(서큘레이터) | 환기 | 현행 이중 정의 해소, 데몬 단독 제어 |
| 17 | 재배대1 AB액 도징펌프 | 도징 | A펌프+B펌프가 릴레이 1개에 병결, 동시 가동(운영자 답변 11) |
| 18 | 재배대1 UV-C | 살균 | |
| 20 | 재배대2 팬 | 환기 | |
| 21 | 재배대1 산 도징펌프 | 도징 | 별도 펌프/별도 릴레이 |
| 22 | 재배대2 AB액 도징펌프 | 도징 | 구성은 17번과 동일 |
| 23 | 재배대2 산 도징펌프 | 도징 | |
| 24, 25, 26 | 재배대2 LED | 조명 | 세 핀 동시 구동 |

**소프트웨어 제어 제외**: GPIO19(재배대2 UV-C)는 별도 하드웨어 타이머 스위치로 운용 중(운영자 답변 13). 코드에서 점유하지 않으며 문서로만 기록한다.

`[확인필요]` 릴레이 보드 입력이 플로팅(미구동) 상태일 때 릴레이가 OFF로 떨어지는지 실측. 제어 데몬 비정상 종료(SIGKILL) 시 lgpio 핸들 해제로 핀이 입력 모드로 풀리는데, 이때 릴레이가 ON으로 떠 있으면 외부 풀업 저항 추가가 필요하다.

### 2.3 시리얼 버스

CH340 USB-RS485 어댑터 2개(동일 모델, 시리얼번호 없음). 어댑터 교체는 없는 것으로 간주하고 소프트웨어로 식별을 보강한다(7.5절).

#### 버스 A: 재배대1 EC/pH 센서

| 항목 | 사양 | 근거 |
|---|---|---|
| 장치 경로 | `/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0` (현행 ttyUSB0) | 현행 코드 |
| 프로토콜 | Modbus RTU | `sensors/Dist_1_EC_pH.py` |
| 통신 설정 | 9600 bps, 8N1, stopbits=1 | 센서 코드 기준. 현행 자동 도징 코드의 stopbits=2는 오기로 보고 1로 통일 `[확인필요]` |
| Slave ID | 1 | |
| 레지스터 맵 | FC3(holding): 0x00=pH, 0x01=EC, 0x02=수온. 스케일링은 현행 `Dist_1_EC_pH.py:107-109` 그대로 이식 (EC raw/10, 수온 raw/10) | |
| 라이브러리 | minimalmodbus (현행 2.1.1 설치본 기준) | |

#### 버스 B: 실내 환경 + 재배대2 EC/pH 센서

| 항목 | 사양 | 근거 |
|---|---|---|
| 장치 경로 | `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` (현행 ttyUSB1) | 현행 코드 |
| 프로토콜 | 독자 ASCII 프로토콜 (제조사 `[확인필요]`). 요청 `node{NNNNNN}\|SensorReq\|{checksum}`, 응답 `\|SensorRes\|{...}\|checksum`, 종결자 없음. 요청 문자열·체크섬·파싱 로직은 현행 코드를 그대로 이식(운영자 답변 9) | `sensors/room_condition.py`, `sensors/Dist_2_EC_pH.py` |
| 통신 설정 | **38400 bps**, 8N1 (운영자 답변 10. 현행 자동 도징의 115200은 수정 누락 버그이며 리뉴얼에서 38400으로 통일) | |
| 노드 주소 | 실내 온습도/CO2: 현행 `room_condition.py` 기준. 재배대2: pH=16, 수온=29, EC=30 | `[확인필요]` 실내 센서 노드 ID 목록을 코드에서 최종 확정 |

#### 버스 접근 규칙

- 버스당 **단일 비동기 버스 매니저 태스크**가 모든 트랜잭션을 직렬화한다. `/tmp` flock 방식은 폐기.
- 한 트랜잭션(요청~응답)의 최대 점유 시간 500ms, 타임아웃 시 버스 해제 후 재시도.

### 2.4 액추에이터 정수

| 항목 | 값 | 근거 |
|---|---|---|
| 도징펌프 유량 | 1.65 mL/s (4대 공통 실측값, 운영자 답변 11) | 설정 파일에 펌프별 항목으로 분리 저장(추후 개별 보정 대비) |
| AB 도징 의미 | A액 펌프와 B액 펌프가 동시 가동, 각각 설정량만큼 투입 | 운영자 답변 11 |

---

## 3. 기능 요구사항

표기: 우선순위 P0(필수, 검수 차단), P1(필수, 출시 전), P2(권장).

### 3.1 시스템 아키텍처 (P0)

systemd 서비스 3개로 구성한다.

```
┌─────────────────────────────────────────────────────────┐
│ skyfarm-control.service  (제어 데몬, 하드웨어 단독 소유)      │
│  - GPIO 전 핀, 시리얼 버스 A/B 소유                         │
│  - 스케줄러(1초 틱) + 도징 엔진 + 안전 워치독                 │
│  - SQLite 기록, 설정 저장소                                │
│  - 내부 API: 127.0.0.1:8301 (REST + WebSocket)            │
├─────────────────────────────────────────────────────────┤
│ skyfarm-web.service  (웹 UI)                              │
│  - 0.0.0.0:8300, FastAPI                                  │
│  - 제어 데몬 API 프록시 + 대시보드/차트/설정 화면              │
├─────────────────────────────────────────────────────────┤
│ skyfarm-camera.service  (카메라 매니저)                     │
│  - /dev/video 단독 소유: MJPEG 스트림 + 정기 촬영 + ML 추정   │
│  - 내부 API: 127.0.0.1:8302                               │
└─────────────────────────────────────────────────────────┘
```

분리 이유: 웹 UI는 변경 빈도가 가장 높다. UI 수정·재시작이 펌프 제어 프로세스에 영향을 주지 않아야 한다.

- 기술 스택: Python 3.11, asyncio, FastAPI + uvicorn. GPIO는 lgpio(Pi 5 네이티브), Modbus는 minimalmodbus, 시리얼은 pyserial.
- 프론트엔드(작성자 재량 위임에 따른 선정): **Jinja2 템플릿 + Alpine.js + Chart.js, WebSocket 실시간 갱신**. Pi 위에서 Node 빌드 체인 없이 유지보수 가능한 구성을 우선했다.
- 각 서비스는 전용 venv를 사용한다(현행 시스템 파이썬 직설치 폐기).

### 3.2 제어 항목별 동작 사양

모든 시간 판정은 로컬 시각(KST) 기준, 스케줄러 틱 1초. 각 항목은 "활성화 플래그(enabled)"를 가지며, enabled=false면 장치 OFF 고정이다. 아래 기본값은 현행 코드에서 추출한 값이며 전부 UI에서 변경 가능해야 한다(3.4절).

#### 조명 (P0)

| 장치 | 핀 | 기본 스케줄 | 동작 |
|---|---|---|---|
| 재배대1 LED | 4 | 04:00 ~ 22:00 ON | 스케줄 구간 내 ON, 외 OFF |
| 재배대2 LED | 24/25/26 동시 | 07:00 ~ 23:00 ON (코드 기준, 운영자 답변 17) | 동일 |

#### 환기 (P0)

| 장치 | 핀 | 기본 스케줄 |
|---|---|---|
| 재배대2 팬 | 20 | 05:00 ~ 21:00 ON |
| 미니팬 | 13 | 05:00 ~ 23:00 ON, 기본 enabled=false (현행 컨텍스트 값) `[확인필요]` 초기 enabled 상태 |
| 공기순환기 | 16 | 24시간 ON, 기본 enabled=true |

#### 살균 (P0)

| 장치 | 핀 | 기본 스케줄 |
|---|---|---|
| 재배대1 UV-C | 18 | 01:00 ~ 05:00 ON |
| 재배대2 UV-C | (없음) | 소프트웨어 제어 제외. 하드웨어 타이머 운용 |

#### 양액 순환펌프 (P0)

| 장치 | 핀 | 기본 스케줄 |
|---|---|---|
| 재배대1 순환펌프 | 5 | 매시 00~04분, 30~34분 ON (5분 × 2회/시간) |
| 재배대2 순환펌프 | 6+12 | 매시 00~02분, 20~22분, 40~42분 ON (3분 × 3회/시간) |

- 스케줄 구간 판정은 매 틱 수행한다. 구간 밖이면 즉시 OFF: 켜짐 고착이 스케줄러 생존 중에는 구조적으로 불가능해야 한다(현행은 ON 명령과 OFF 명령이 별개 이벤트라 OFF 유실 가능).
- 순환펌프 동작/정지 이벤트는 DB와 CSV에 기록한다(5.3절, 운영자 답변 25).

#### EC/pH 자동 도징 (P0)

| 항목 | 재배대1 | 재배대2 |
|---|---|---|
| 기본 실행 주기 | 4시간 슬롯(00/04/08/12/16/20시) | 동일 |
| 측정 방식 | 현행 코드 기준: 20초간 1초 간격 샘플 평균 `[확인필요]` 현행 로직 재확인 후 이식 | 3회 샘플 중앙값, 3회 중 2회 이상 유효 필요 |
| 유효범위 | EC 0~3.0 mS/cm, pH 3.5~10.0, 수온 10~50°C | 동일 |
| AB 투입 조건 | EC ≤ 1.1 | EC ≤ 1.1 |
| 산 투입 조건 | pH ≥ 5.9 | pH ≥ 5.9 |
| 기본 투입량 | AB 5mL, 산 5mL | AB 50mL, 산 50mL (탱크 용량 차이, 운영자 답변 12) |
| 기본 enabled | **false** (재배대1은 의도된 휴지 중, 운영자 답변 2) | true |

- 투입 시간 = 투입량 ÷ 1.65 mL/s. 투입 중에도 스케줄러/명령 처리가 멈추지 않아야 한다(현행 Dist_2의 blocking sleep 금지). asyncio 태스크로 구현하고 취소 가능해야 한다.
- 실행 주기(슬롯 간격), 투입량, EC/pH 임계값은 UI에서 재배대별로 편집 가능(운영자 답변 6, 12, 16).
- 자동 도징 enabled 토글을 재배대별로 UI에 제공(운영자 답변 6).
- 측정값이 유효 조건을 충족하지 못하면 해당 슬롯의 투입을 건너뛰고 skip 사유를 기록한다(7.1절).

#### 수동 도징 (P0)

- UI에서 재배대 선택 + 펌프 종류(AB/산) + 투입량(mL) 입력 → 즉시 투입.
- 입력 범위 검증: 0.1 ≤ mL ≤ 200 `[확인필요]` 상한값.
- **수동 우선 원칙**(운영자 답변 8): 자동 도징 진행 중 수동 명령 수신 시, 진행 중인 자동 투입을 즉시 중단(펌프 OFF)하고 수동 투입을 실행한다. 중단된 자동 투입은 재개하지 않고 "preempted"로 기록한다.
- 동일 재배대에서 도징 작업은 동시에 1건만 실행한다(직렬화).

#### 카메라/생육 모니터링 (P1)

- skyfarm-camera 서비스가 카메라 장치를 단독 소유한다. mjpg-streamer는 폐기하고, 같은 프로세스가 (a) MJPEG 라이브 스트림 제공, (b) 일 2회(기본 06:00, 18:00) 정지 영상 촬영, (c) 현행 ML 파이프라인(특징 추출 → 회귀 모델 캐스케이드)으로 무게/생육 추정, (d) `camera_butterhead_weight_log`/`growth_log` 기록을 수행한다. 장치 경합(pkill 중재) 원천 제거.
- ML 파이프라인 코드(특징 추출, 회귀, 자동 재학습, 부트스트랩 휴리스틱)는 현행 `camera/` 모듈을 그대로 이식하고 호출 구조만 교체한다.
- plant-id / batch-id / 촬영 시각은 UI 설정 화면에서 변경 가능(현행은 env 수정 + 서비스 재시작).
- 스트림은 웹 UI 대시보드에 임베드한다(8300 포트 경유 프록시, 8302 직접 노출 안 함).

### 3.3 재시작/정전 복구 동작 (P0, 운영자 답변 7·23)

- 제어 데몬 기동 시퀀스:
  1. 모든 출력 핀 클레임 후 **안전 상태로 초기화: 도징·순환 펌프 = OFF, 나머지 = OFF**
  2. 시간 동기화 확인(4.3절) 후 스케줄러 시작
  3. 첫 틱에서 현재 시각 기준 원하는 상태(desired state)를 계산해 일괄 적용
- 예시: 16:00 재시작 → LED1/LED2/팬2 ON, 순환펌프는 매시 00~02분 등 구간 판정에 따라 동작, UV OFF.
- 자동 도징의 슬롯 실행 여부는 "마지막 실행 슬롯" 기록과 비교한다. 재시작으로 슬롯 정각을 지나쳤으면 해당 슬롯은 건너뛴다(중복 투입 방지가 누락 투입보다 우선) `[확인필요]` 지나친 슬롯을 소급 실행할지 여부.
- 배포/재부팅 중 제어 중단은 허용된다(운영자 답변 23). 단 모든 서비스는 `Restart=always`로 자동 복구한다.

### 3.4 UI 편집 가능 파라미터 (P0, 운영자 답변 16)

| 분류 | 항목 |
|---|---|
| 조명 | LED1/LED2 ON·OFF 시각 |
| 환기 | 팬2/미니팬 ON·OFF 시각, 공기순환기 24시간 여부, 각 enabled |
| 살균 | UV1 ON·OFF 시각, enabled |
| 순환 | 순환펌프1/2의 시간당 가동 구간(시작분, 지속분, 횟수), enabled |
| 자동 도징 | 재배대별 enabled, 실행 주기(시간 단위), EC 임계값, pH 임계값, AB 투입량(mL), 산 투입량(mL) |
| 도징 공통 | 펌프 유량(mL/s, 펌프별) |
| 로깅 | 순환펌프 CSV 기록 on/off (운영자 답변 25) |
| 카메라 | 촬영 시각, plant-id, batch-id |

**UI 편집 불가(코드 상수)**: 센서 캘리브레이션 수식. 재배대2 보정(EC −0.3, pH +0.3)은 센서 모듈 코드에 수식·교정일·기준기를 주석으로 명기한 상수로 둔다(운영자 답변 18). 센서 유효범위(EC 0~3.0 등)도 안전 관련 상수로서 코드에 둔다.

---

## 4. 비기능 요구사항

### 4.1 안전 인터록 (P0)

펌프 ON 고착은 본 시스템 최대 리스크다(1.2절). 아래를 모두 구현한다.

1. **상태 기반 제어**: 펌프류는 "ON 이벤트 + OFF 이벤트" 모델을 금지하고, 매 틱 desired state를 계산해 적용한다. 스케줄러가 살아 있는 한 구간 밖 ON은 1초 내 해소된다.
2. **도징 최대 가동 시간 워치독**: 도징 1건의 최대 ON 시간 = 계산된 투입 시간 × 1.2. 절대 상한 120초 `[확인필요]` (50mL 기준 30.3초이므로 여유 충분). 초과 시 강제 OFF + 안전 이벤트 기록.
3. **독립 워치독 태스크**: 제어 로직과 별도의 asyncio 태스크가 1초마다 실제 핀 출력값과 desired state를 대조한다. 불일치 3회 연속 시 해당 핀 강제 OFF + 안전 이벤트 기록.
4. **종료 핸들러**: SIGTERM/SIGINT 수신 시 모든 펌프 핀에 OFF(1) 출력 후 정상 종료. systemd `TimeoutStopSec=10`.
5. **systemd 워치독**: `WatchdogSec=30`, 데몬은 메인 루프에서 `sd_notify(WATCHDOG=1)` 송신. 메인 루프 행(hang) 시 systemd가 재시작 → 기동 시퀀스의 펌프 OFF로 복구.
6. **도징 직렬화 + 수동 우선**: 3.2절 수동 도징 항 참조.
7. 일일 최대 투입량 한도는 두지 않는다(운영자 답변 6).

### 4.2 안정성/가용성 (P0)

- 서비스 3종 모두 `Restart=always`, `RestartSec=5`.
- 제어 데몬은 웹 UI/카메라 서비스가 죽어도 단독으로 전 제어를 지속한다.
- 센서/버스 장애가 조명·환기·순환펌프 스케줄 제어를 막아서는 안 된다(도징만 센서 의존).
- 메모리: 장기 가동을 전제로 무한 성장 자료구조 금지(현행 스왑 소진 이력). 인메모리 시계열 버퍼는 고정 길이 deque로 제한.

### 4.3 시간 정확성 (P0)

- Pi 5에 RTC 백업 전원이 없으므로, 제어 데몬 유닛에 `After=time-sync.target` + `systemd-time-wait-sync.service` enable을 명시한다. 시간 동기 전에는 스케줄 판정을 시작하지 않는다(현행 nodered.service에서 주석 처리됐던 보호의 복원).
- 동기 실패가 10분 지속되면 마지막 동기 시각 기준으로 제어를 시작하되 경고 상태를 UI에 표시 `[확인필요]` 오프라인 운전 허용 여부.

### 4.4 로깅 (P1)

- 구조화 로깅(Python logging, 파일 회전): 서비스별 `/var/log/skyfarm/{service}.log`, 10MB × 5개 회전. 현행 "stdout JSON이 유일한 관측 수단" 상태 해소.
- 기록 의무 이벤트: 모든 릴레이 상태 변화(원인 포함: schedule/manual/auto_dosing/safety), 도징 시작·완료·중단(사유), 센서 read 실패, 버스 재연결, 설정 변경(이전값→새값), 안전 워치독 발동.
- 장애 외부 알림(텔레그램 등)은 구현하지 않는다(운영자 답변 22).

### 4.5 응답속도 (P1)

| 항목 | 목표 |
|---|---|
| 수동 도징 버튼 → 펌프 ON | ≤ 1초 |
| 설정 변경 → 제어 반영 | 다음 스케줄러 틱(≤ 1초) |
| 스케줄 경계(예: 22:00 LED OFF) 정확도 | ± 2초 |
| 대시보드 센서 갱신 | 센서 폴링 주기와 동일(10초)를 WebSocket push. "라이브" 요건 충족(운영자 답변 19) |
| 웹 UI 페이지 로드(LAN) | ≤ 2초 |

---

## 5. 데이터 / 통신 사양

### 5.1 변수 정의

| 변수명 | 단위 | 유효범위 | 출처 | 폴링 | DB 기록 |
|---|---|---|---|---|---|
| `room.temp` | °C | 현행 코드 기준 `[확인필요]` | 버스 B | 10초 | 20분 슬롯(00/20/40분) |
| `room.humi` | %RH | 0~100 | 버스 B | 10초 | 20분 슬롯 |
| `room.co2` | ppm | 현행 코드 기준 `[확인필요]` | 버스 B | 10초 | 20분 슬롯 |
| `d1.ec` | mS/cm | 0~3.0(유효) | 버스 A | 10초 | 20분 슬롯 |
| `d1.ph` | pH | 3.5~10.0(유효) | 버스 A | 10초 | 20분 슬롯 |
| `d1.solution_temp` | °C | 10~50(유효) | 버스 A | 10초 | 20분 슬롯 |
| `d2.ec` | mS/cm | 0~3.0(유효), 보정 −0.3 적용 후 | 버스 B | 10초 | 20분 슬롯 |
| `d2.ph` | pH | 3.5~10.0(유효), 보정 +0.3 적용 후 | 버스 B | 10초 | 20분 슬롯 |
| `d2.solution_temp` | °C | 10~50(유효) | 버스 B | 10초 | 20분 슬롯 |
| `actuator.{name}` | enum | `on`/`off` | GPIO | 상태 변화 시 | 이벤트 기록 |
| `camera.weight_est` | g | 8~450 (현행 클램프) | 카메라 서비스 | 일 2회 | 촬영 시 |

- 센서값에는 `ts`(측정 시각)와 `stale` 플래그를 항상 동반한다. 마지막 성공 측정으로부터 60초 경과 시 stale=true.

### 5.2 설정 저장소

- 위치: `/home/cja/Work/skyfarm-control/config/settings.json` `[확인필요]` 설치 경로. 원자적 쓰기(임시파일 + rename).
- 변경 이력: DB `config_history` 테이블에 (시각, 키, 이전값, 새값) 기록.
- 스키마(기본값 = 현행 코드 추출값):

```json
{
  "lighting": {
    "d1_led":  { "enabled": true,  "on": "04:00", "off": "22:00" },
    "d2_led":  { "enabled": true,  "on": "07:00", "off": "23:00" }
  },
  "ventilation": {
    "d2_fan":     { "enabled": true,  "on": "05:00", "off": "21:00" },
    "mini_fan":   { "enabled": false, "on": "05:00", "off": "23:00" },
    "circulator": { "enabled": true,  "always_on": true }
  },
  "uv": {
    "d1_uv": { "enabled": true, "on": "01:00", "off": "05:00" }
  },
  "circulation": {
    "d1_pump": { "enabled": true, "windows_per_hour": [{"start_min": 0, "duration_min": 5}, {"start_min": 30, "duration_min": 5}] },
    "d2_pump": { "enabled": true, "windows_per_hour": [{"start_min": 0, "duration_min": 3}, {"start_min": 20, "duration_min": 3}, {"start_min": 40, "duration_min": 3}] }
  },
  "dosing": {
    "d1": { "auto_enabled": false, "interval_hours": 4, "ec_min": 1.1, "ph_max": 5.9, "ab_volume_ml": 5.0,  "acid_volume_ml": 5.0 },
    "d2": { "auto_enabled": true,  "interval_hours": 4, "ec_min": 1.1, "ph_max": 5.9, "ab_volume_ml": 50.0, "acid_volume_ml": 50.0 },
    "pump_flow_ml_per_sec": { "d1_ab": 1.65, "d1_acid": 1.65, "d2_ab": 1.65, "d2_acid": 1.65 },
    "manual_max_ml": 200
  },
  "logging": { "pump_csv_enabled": true },
  "camera": { "capture_times": ["06:00", "18:00"], "plant_id": "butterhead-02", "batch_id": "batch-2026-04" },
  "web": { "port": 8300, "base_url": "" }
}
```

`web.base_url`은 추후 Cloudflare 도메인 연결 시 리버스 프록시 하위 경로/호스트 대응용(운영자 답변 20).

### 5.3 데이터베이스

- 파일: 현행 `/home/cja/Work/cja-skyfarms-project/data/data.db` 유지(이력 연속성). WAL 모드, `busy_timeout=5000ms`, 데몬이 1시간마다 `wal_checkpoint(TRUNCATE)` 수행.
- writer: 제어 데몬(센서/이벤트/도징), 카메라 서비스(생육 로그). 웹 UI는 읽기 전용.
- 기존 테이블(`Temp_humi_log`, `Dist_1_EC_pH_log`, `Dist_2_EC_pH_log`, `Dist_1/2_Solution_input_log`, `camera_butterhead_*`)은 스키마·컬럼명을 유지한 채 계속 기록한다(차트 연속성).
- 추가 마이그레이션:

```sql
-- 투입 이력에 현행에서 유실되던 정량 정보 추가 (NULL 허용으로 하위 호환)
ALTER TABLE Dist_1_Solution_input_log ADD COLUMN volume_ml REAL;
ALTER TABLE Dist_1_Solution_input_log ADD COLUMN duration_s REAL;
ALTER TABLE Dist_1_Solution_input_log ADD COLUMN source TEXT;      -- 'auto' | 'manual' | 'preempted'
ALTER TABLE Dist_2_Solution_input_log ADD COLUMN volume_ml REAL;
ALTER TABLE Dist_2_Solution_input_log ADD COLUMN duration_s REAL;
ALTER TABLE Dist_2_Solution_input_log ADD COLUMN source TEXT;

CREATE TABLE IF NOT EXISTS actuator_event_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,            -- ISO8601
  device TEXT NOT NULL,        -- 'd1_led', 'd2_pump', ...
  state TEXT NOT NULL,         -- 'on' | 'off'
  cause TEXT NOT NULL          -- 'schedule' | 'manual' | 'auto_dosing' | 'safety' | 'startup'
);

CREATE TABLE IF NOT EXISTS dosing_skip_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  rack TEXT NOT NULL,          -- 'd1' | 'd2'
  reason TEXT NOT NULL         -- 'sensor_invalid' | 'sensor_stale' | 'disabled' | 'slot_missed'
);

CREATE TABLE IF NOT EXISTS config_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  key TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT
);

-- 중복 인덱스 정리 (현행: Dist_2 Date 인덱스 3중, Temp_humi 2중)
DROP INDEX IF EXISTS idx_dist2_ecph_date;
DROP INDEX IF EXISTS idx_d2_date;
```

- **CSV 이중 기록**(운영자 답변 25): 순환펌프 동작/정지를 현행 형식대로 `data/Dist_1_pump_activate_result.csv`, `data/Dist_2_pump_activate_result.csv`에 기록(fsync 포함). 설정 `logging.pump_csv_enabled=false`로 중단 가능. 기본값 true(첫 배포 후 검증용).
- **백업**(운영자 답변 24): 보존 기간 영구, 삭제 정책 없음. 매일 03:00 `sqlite3 data.db ".backup"` 스냅샷 + gzip 후 git 커밋·푸시하는 systemd timer 제공. `[확인필요]` 백업용 git 원격 저장소 주소와 인증 방식.

### 5.4 내부 API 맵 (제어 데몬, 127.0.0.1:8301)

| 메서드/경로 | 기능 | 본문/응답 요약 |
|---|---|---|
| `GET /api/v1/status` | 전 장치 상태 + 센서 최신값 + stale 플래그 | `{devices: {...}, sensors: {...}, safety: {...}}` |
| `GET /api/v1/config` | 설정 전체 조회 | 5.2절 스키마 |
| `PUT /api/v1/config` | 설정 변경(부분 갱신 허용, 검증 후 적용) | 변경된 키 목록 |
| `POST /api/v1/devices/{id}/enabled` | 장치 enabled 토글 | `{"enabled": true}` |
| `POST /api/v1/dosing/manual` | 수동 도징 | `{"rack":"d2","pump":"ab","volume_ml":50}` → `{"job_id":...}` |
| `POST /api/v1/dosing/abort` | 진행 중 도징 중단 | `{"rack":"d2"}` |
| `GET /api/v1/logs/dosing?from=&to=` | 투입 이력 | |
| `GET /api/v1/history/{table}?from=&to=&limit=` | 시계열 조회(차트용, 다운샘플 지원) | |
| `WS /api/v1/ws` | 이벤트 스트림 | 아래 메시지 스키마 |

WebSocket 메시지:

```json
{"type": "sensor",   "ts": "...", "values": {"d1.ec": 1.32, "d1.ph": 5.8, "...": 0}}
{"type": "actuator", "ts": "...", "device": "d2_ab_pump", "state": "on", "cause": "auto_dosing"}
{"type": "dosing",   "ts": "...", "rack": "d2", "event": "started|finished|aborted|preempted|skipped", "detail": {}}
{"type": "safety",   "ts": "...", "event": "watchdog_forced_off", "device": "..."}
```

웹 UI(8300)는 위 API를 동일 경로로 프록시하고, CSV 다운로드(`GET /download_csv?table=&from=&to=`, 화이트리스트 검증)를 추가 제공한다.

---

## 6. UI / 모니터링 요구사항

### 6.1 접속/인증 (운영자 답변 20)

- 바인딩 `0.0.0.0:8300`. 현행 외부 접속(`http://1.217.132.157:8300/...`)과 동일 포트. `[확인필요]` 현재 라우터 포트포워딩이 8300→1880(Node-RED)이므로, 컷오버 시 8300→8300으로 변경 필요.
- 인증 없음(운영자 결정).
  **작성자 권고(미적용, 기록만)**: 공인 IP에 무인증으로 도징 펌프 조작이 노출되는 구성이다. 최소한 도징/설정 변경 요청에만 4자리 PIN을 두는 방안을 재고 권장. 본 시방서는 운영자 결정대로 무인증으로 작성하되, 인증 모듈을 끼울 수 있는 미들웨어 훅만 마련한다.
- Cloudflare 도메인 연결 대비: 포트·base URL을 설정 파일로 외부화, 리버스 프록시 헤더(X-Forwarded-*) 처리.

### 6.2 화면 구성 (P0)

| 화면 | 내용 |
|---|---|
| 대시보드 | 센서 게이지(실내 온/습/CO2, 재배대1·2 EC/pH/수온) 10초 라이브 갱신, 전 장치 상태 표시(ON/OFF/사유), stale·버스 장애 경고 배지, 카메라 라이브 스트림 임베드, 최근 생육 추정값 |
| 제어 | 장치별 enabled 토글, 수동 도징(재배대/펌프/mL 입력 + 실행/중단 버튼), 자동 도징 재배대별 토글, 진행 중 도징 표시(남은 시간) |
| 차트 | 기간 선택(기본 7일) EC/pH/수온/온습도/CO2 이력, 투입 이벤트 마커 오버레이, 생육(무게 추정) 추이 |
| 데이터 | 테이블 뷰(화이트리스트 테이블), 날짜 범위 CSV 다운로드 |
| 설정 | 3.4절 파라미터 전체 편집 폼(입력 검증 + 저장 시 즉시 반영), 설정 변경 이력 열람 |

### 6.3 UI 일반 원칙

- 토글 의미는 정방향으로 통일한다(ON=true). 현행 onvalue=false 반전 폐기.
- 모든 제어 조작은 1초 내 실제 장치 상태가 화면에 반영(WebSocket 에코)되어야 한다. 조작 실패 시 명시적 에러 토스트.
- 모바일 브라우저(폭 375px)에서 대시보드와 제어 화면이 조작 가능해야 한다(P1).

---

## 7. 예외 / 장애 처리

### 7.1 센서 이상 (P0)

| 상황 | 동작 |
|---|---|
| 단발 read 실패/CRC 오류 | 즉시 2회 재시도. 실패 시 해당 폴링 회차 결측 처리(마지막 값 유지 + stale 카운트) |
| 60초 이상 연속 실패 | stale=true, 대시보드 경고 배지. DB에는 결측으로 기록(가짜 값 기록 금지) |
| 유효범위 밖 측정값 | 폐기 + 카운트. 자동 도징 판단에 사용 금지 |
| 자동 도징 시점에 유효 샘플 부족 | 해당 슬롯 투입 skip, `dosing_skip_log` 기록, UI 표시. 다음 슬롯에서 재시도 |

센서 이상이 자동 도징 외 제어(조명/환기/순환)에 영향을 주지 않는다. 자동 도징 자체는 UI 토글로 끌 수 있다(운영자 답변 6).

### 7.2 시리얼 버스 두절 (P0)

- 포트 open 실패/IO 에러 시: 포트 close 후 지수 백오프(1, 2, 4, ... 최대 60초)로 무한 재연결. 프로세스는 죽지 않는다(현행 import 시점 즉사 구조 폐기).
- 버스 단위 상태(`ok`/`degraded`/`down`)를 status API와 UI에 노출.

### 7.3 도징 중 장애 (P0)

- 도징 태스크 예외 발생 시: finally에서 해당 펌프 핀 OFF 보장 + `aborted` 기록.
- 데몬 비정상 종료 시: systemd 재시작 → 기동 시퀀스에서 전 펌프 OFF(3.3절). 4.1절 워치독 체계와 합쳐 펌프 고착 노출 시간을 "데몬 사망~재기동(수 초)"으로 한정한다.

### 7.4 DB 장애 (P1)

- DB 쓰기는 큐 경유 비동기 처리: DB 잠금/오류가 제어 루프를 블로킹하지 않는다.
- 쓰기 실패 시 큐에 보존(최대 1,000건) 후 재시도, 초과분은 가장 오래된 것부터 폐기 + 로그.

### 7.5 시리얼 포트 식별 (P0)

CH340 어댑터 2개가 동일 USB ID라 재부팅/재배선 시 ttyUSB0/1이 뒤바뀔 수 있다(현행 구조 위험). 어댑터 교체 없이 소프트웨어로 보강한다:

1. 기본 식별: 현행과 동일한 by-path(버스 A)/by-id(버스 B) 경로 사용.
2. **기동 시 프로브 검증**: 버스 A로 식별된 포트에 Modbus FC3 slave 1 read를 시도한다. 응답이 없고 버스 B 포트에서 응답이 오면 두 포트가 뒤바뀐 것으로 판단, 자동으로 교차 매핑하고 경고 로그를 남긴다. 프로브 양쪽 모두 실패 시 버스 down 상태로 두고 재시도(7.2절).
3. `[확인필요]` 현재 어댑터의 실제 물리 USB 포트 위치를 고정(라벨링)할 수 있는지. 가능하면 by-path 2개로 통일하는 것이 가장 단순하다.

### 7.6 카메라 장애 (P1)

- 프레임 획득 실패 누적 시(연속 30초): 현행과 동일하게 `usbreset 046d:0825` 실행 후 장치 재오픈. `[확인필요]` sudoers의 usbreset NOPASSWD 항목 유지.
- 촬영 실패 시 다음 정기 시각까지 대기(소급 촬영 없음), 실패 기록.
- 카메라 서비스 장애는 제어 데몬에 영향 없음.

### 7.7 시간 동기 장애

- 4.3절 참조.

---

## 8. 기존 시스템 대비 변경점

| # | 항목 | 현행 (AS-IS) | 리뉴얼 (TO-BE) |
|---|---|---|---|
| 1 | 실행 구조 | Node-RED가 pythonshell로 Python 12개를 자식 구동 | Python systemd 서비스 3개(control/web/camera). Node-RED 완전 제거 |
| 2 | 도징 OFF 경로 | stdout JSON → Node-RED 파싱 → GPIO 노드 (유실 가능) | 단일 프로세스 내 직접 제어 + 워치독 3중화 (4.1절) |
| 3 | 펌프 제어 모델 | ON/OFF 이벤트 분리(OFF 유실 가능) | 매 틱 desired state 적용(고착 구조적 차단) |
| 4 | GPIO 소유 | Node-RED 5핀 + Python 10핀 분산, 핀 16 이중 정의 | 제어 데몬 단독 소유. GPIO19(UV2)는 하드웨어 타이머로 제어 제외 |
| 5 | 시리얼 접근 | 프로세스 3개가 /tmp flock 공유, 20초 락 점유 | 버스당 단일 매니저 태스크 직렬화 |
| 6 | 보레이트 | 센서 38400 / 자동도징 115200 불일치(버그) | 38400 통일 (운영자 답변 10) |
| 7 | 설정값 | 12개 파일에 하드코딩, 변경=소스 수정 | settings.json + UI 편집 + 변경 이력 DB |
| 8 | 캘리브레이션 | Dist_2 EC −0.3 / pH +0.3 하드코딩(문서 없음) | 코드 상수 유지하되 수식·교정일 주석 명기. UI 편집 불가 (운영자 답변 18) |
| 9 | 프로세스 감시 | 자식 사망 시 방치(12개 중 9개만 생존) | systemd Restart=always + WatchdogSec |
| 10 | 재시작 복구 | 일부 장치 미초기화, 상태 비결정 | 시각 기준 전 장치 상태 재계산 (운영자 답변 7) |
| 11 | 수동/자동 도징 경합 | 인터록 없음(last-write-wins) | 직렬화 + 수동 우선(preempt) (운영자 답변 8) |
| 12 | UI | node-red-dashboard(고아 위젯 13개, 스위치 의미 반전) | FastAPI + Jinja2 + Alpine.js, 정방향 토글, WebSocket 라이브 |
| 13 | 원격 접속 | remote-red 터널 + 포트포워딩 8300→1880 | 포트포워딩 8300→8300 직결, remote-red 제거, Cloudflare 대비 base_url 외부화 |
| 14 | 카메라 | mjpg-streamer vs 촬영 스크립트가 pkill로 경합, 일 2회 usbreset 연명 | 단일 카메라 서비스가 스트림+촬영+ML 통합 소유 |
| 15 | 도징 이력 | volume/duration 미저장 | volume_ml, duration_s, source 컬럼 추가 |
| 16 | DB 운영 | 다중 writer, busy_timeout 없음, 체크포인트 방치, 중복 인덱스 | writer 2개로 축소, busy_timeout 5s, 주기 체크포인트, 인덱스 정리 |
| 17 | 백업 | 없음 | 일일 DB 스냅샷 git 푸시 (운영자 답변 24) |
| 18 | CSV 기록 | 무조건 기록 | 설정 토글(기본 ON, 안정화 후 OFF 가능) (운영자 답변 25) |
| 19 | 시간 동기 | 부팅 시 동기 대기 주석 처리됨 | time-sync 대기 복원 (4.3절) |
| 20 | 폐기 항목 | Node-RED 전체, main.py(Tkinter), *_origin.py, old_version/, OpenWeather 연동, remote-red, mjpg-streamer, 깨진 /etc/systemd/system/mjpg-streamer.service | 제거(소스는 git 이력으로 보존) |

**변경 없음(명시)**: 센서 프로토콜·파싱·폴링 주기(10초)·기록 주기(20분), EC/pH 임계값·투입량 기본값, 스케줄 기본값, data.db 파일·기존 테이블 스키마, plant_factory.db와 식물 현황 앱(범위 외), 카메라 하드웨어, UV2 하드웨어 타이머 운용.

### 8.1 디렉터리 구조(안)

```
/home/cja/Work/skyfarm-control/        # 신규 저장소 [확인필요] 경로/저장소 분리 여부
├── control/                           # skyfarm-control.service
│   ├── main.py                        # 기동 시퀀스, asyncio 루프
│   ├── hw/
│   │   ├── gpio.py                    # lgpio 래퍼, active-low 추상화, 핀맵
│   │   ├── bus_modbus.py              # 버스 A 매니저 (minimalmodbus)
│   │   └── bus_ascii.py               # 버스 B 매니저 (현행 프로토콜 이식)
│   ├── sensors/
│   │   ├── d1_ecph.py                 # 캘리브레이션 상수+주석 포함
│   │   ├── d2_ecph.py
│   │   └── room.py
│   ├── devices/                       # 장치별 desired-state 계산
│   │   ├── lighting.py, ventilation.py, uv.py, circulation.py
│   │   └── dosing.py                  # 자동/수동 도징 엔진, preempt
│   ├── safety.py                      # 워치독, 최대 가동시간, 종료 핸들러
│   ├── scheduler.py                   # 1초 틱, 상태 적용
│   ├── store.py                       # SQLite(큐 경유), CSV, 체크포인트
│   ├── config.py                      # settings.json 로드/검증/이력
│   └── api.py                         # 내부 REST+WS (8301)
├── web/                               # skyfarm-web.service (8300)
│   ├── main.py, proxy.py
│   ├── templates/                     # Jinja2
│   └── static/                        # Alpine.js, Chart.js
├── camera/                            # skyfarm-camera.service (8302)
│   ├── main.py                        # 장치 소유, 스트림+촬영 스케줄
│   └── (현행 camera/ ML 모듈 이식)
├── config/settings.json
├── migrations/                        # 5.3절 DDL
├── systemd/                           # 유닛 파일 3종 + backup.timer
└── tests/
```

### 8.2 컷오버 절차

1. 신규 스택을 서비스 disabled 상태로 설치, 마이그레이션 DDL 적용.
2. **검증 모드 운전**: Node-RED 정지 시간대에 신규 데몬을 dry-run 플래그(GPIO 출력 대신 로그)로 기동, 센서 판독·스케줄 계산 검증. 시리얼 버스는 동시 점유 불가하므로 Node-RED 가동 중 병행 테스트는 하지 않는다.
3. 컷오버(제어 중단 허용됨, 운영자 답변 23): `systemctl disable --now nodered` → 신규 서비스 3종 enable → 9장 검수 체크리스트 수행. 도징 슬롯 정각(00/04/.../20시)을 피해 실시.
4. 라우터 포트포워딩 8300→8300 변경.
5. 롤백 경로: 신규 서비스 disable → nodered re-enable (컷오버 후 2주간 Node-RED 설치본 보존).
6. 안정화 확인 후(CSV 대조 포함) Node-RED 제거 및 폐기 목록(8장 #20) 정리.

---

## 9. 테스트 / 검수 기준

### 9.1 단위 테스트 (pytest, 하드웨어 비의존)

| ID | 항목 | 합격 기준 |
|---|---|---|
| U-01 | 스케줄 판정 함수 | 경계값(정각, 자정 걸침, 구간 밖) 전부 정확. LED1 04:00:00=ON, 03:59:59=OFF 등 |
| U-02 | 순환펌프 시간창 판정 | 매시 0~4분 등 구간 경계 ±1초 정확 |
| U-03 | 도징 시간 계산 | 50mL ÷ 1.65 = 30.30초(±0.01), 워치독 한계 = 36.4초 |
| U-04 | 자동 도징 판단 | EC=1.1→투입, 1.11→미투입; pH=5.9→투입, 5.89→미투입; 유효 샘플 1/3→skip |
| U-05 | ASCII 프로토콜 파서 | 현행 코드의 실제 응답 캡처 데이터로 회귀 테스트(깨진 프레임 포함) |
| U-06 | Modbus 응답 파싱 | 스케일링(EC /10, 수온 /10) 정확 |
| U-07 | 설정 검증 | 범위 밖 값(투입량 음수, 시각 형식 오류) 거부 |
| U-08 | 캘리브레이션 적용 | d2 raw EC 1.6 → 1.3, raw pH 5.6 → 5.9 |

### 9.2 하드웨어 통합 테스트 (실기, 양액 라인 분리 또는 물로 대체)

| ID | 항목 | 합격 기준 |
|---|---|---|
| H-01 | 전 릴레이 구동 | 14핀(4,5,6,12,13,16,17,18,20,21,22,23,24/25/26) 각각 ON/OFF 시 해당 장치만 동작 |
| H-02 | 센서 연속 판독 | 두 버스 동시 10초 폴링으로 24시간 무중단, read 실패율 < 1% |
| H-03 | 버스 직렬화 | 자동 도징 측정 중에도 센서 폴링 지연 < 2초(현행 flock 20초 점유 해소 확인) |
| H-04 | 보레이트 38400 | 자동 도징의 d2 센서 판독 성공률이 센서 스크립트와 동등 |
| H-05 | 포트 스왑 프로브 | USB 어댑터 두 개를 맞바꿔 꽂고 재부팅 → 자동 교차 매핑 + 경고 로그, 제어 정상 |
| H-06 | 수동 도징 정량 | 10mL 지령 → 실측 토출량 10mL ± 10% (4펌프 각각) |

### 9.3 시나리오 테스트 (검수 차단 항목)

| ID | 시나리오 | 합격 기준 |
|---|---|---|
| S-01 | **도징 중 데몬 강제 종료**: 50mL 투입 중 `kill -9` | systemd 재기동 후 5초 내 전 펌프 OFF. 펌프 ON 지속 시간 ≤ 10초 |
| S-02 | **도징 중 정상 재시작**: 투입 중 `systemctl restart` | SIGTERM 핸들러가 펌프 OFF 후 종료, 재기동 후 aborted 기록 존재 |
| S-03 | **16:00 재시작 복구**: 16:00에 재부팅 | LED1/LED2/팬2 ON, UV OFF, 순환펌프는 분 구간에 맞게 동작, 도징 슬롯 중복 실행 없음 |
| S-04 | **자정 걸침**: 23:50~00:10 연속 운전 | UV1이 01:00에 ON, LED 자정 상태 정확 |
| S-05 | **수동 우선**: 자동 도징 진행 중 수동 도징 명령 | 자동 즉시 중단(preempted 기록), 수동 정량 실행 |
| S-06 | **센서 무효 시 skip**: 센서 케이블 분리 후 도징 슬롯 도래 | 투입 0회, skip 기록, 조명/환기/순환 제어는 정상 지속 |
| S-07 | **버스 두절 복구**: USB 어댑터 발거 후 재삽입 | 60초 내 자동 재연결, 프로세스 생존 |
| S-08 | **워치독**: 도징 태스크를 인위적으로 행 시킨 상태 | 최대 가동 시간 초과 시 강제 OFF + safety 이벤트 |
| S-09 | **시간 미동기 부팅**: 네트워크 차단 부팅 | 스케줄 제어 보류 + 경고 표시, 동기 후 자동 시작 |
| S-10 | **UI 라이브**: 대시보드 열고 센서값 변화 유발 | 10초 내 화면 갱신, 외부망(공인 IP:8300)에서 동일 동작 |
| S-11 | **설정 즉시 반영**: LED OFF 시각을 현재 시각 −1분으로 변경 | 1초 내 LED OFF, config_history 기록 |
| S-12 | **CSV 토글**: pump_csv_enabled off→on | 기록 중단/재개 정확, 파일 형식 현행과 동일 |
| S-13 | **카메라 통합**: 06:00 정기 촬영 시각에 스트림 시청 중 | 촬영·무게 추정·DB 기록 성공, 스트림 중단 ≤ 30초, pkill 미사용 |
| S-14 | **웹 서비스 격리**: skyfarm-web 강제 종료 | 제어 데몬 무영향, 스케줄 제어 지속 |

### 9.4 안정화 검수 (배포 후)

| ID | 항목 | 합격 기준 |
|---|---|---|
| A-01 | 14일 연속 운전 | 데몬 비정상 재시작 0회, 메모리 증가 < 20MB, safety 이벤트 0회 |
| A-02 | 순환펌프 CSV 대조 | 14일간 CSV 기록과 스케줄 기대값 일치(누락/과잉 가동 0회) (운영자 답변 25의 검증 목적 충족) |
| A-03 | 도징 정합성 | 투입 이력의 volume/duration이 설정값과 일치, EC/pH 추이가 투입 이벤트와 정합 |
| A-04 | DB/백업 | 20분 슬롯 센서 기록 누락 < 0.5%, 일일 git 백업 14회 전부 성공 |
| A-05 | 시각 정확도 | 스케줄 경계 이벤트의 실제 발생 시각 오차 ± 2초 (actuator_event_log 기준) |

---

## 부록 A. [확인필요] 목록 (코딩 착수 전 확정)

| # | 항목 | 관련 절 |
|---|---|---|
| 1 | 릴레이 보드 입력 플로팅 시 거동(풀업 유무) 실측 | 2.2 |
| 2 | 버스 A stopbits 1로 통일 시 자동 도징 판독 정상 여부 실측 | 2.3 |
| 3 | 버스 B 센서 제조사/모델명(문서화용) 및 실내 센서 노드 ID 목록 | 2.3, 5.1 |
| 4 | 재배대1 자동 도징의 현행 측정 로직(20초 평균) 코드 재확인 | 3.2 |
| 5 | 미니팬 초기 enabled 기본값 | 3.2 |
| 6 | 재시작으로 지나친 도징 슬롯의 소급 실행 여부(시방 기본: 건너뜀) | 3.3 |
| 7 | 수동 도징 1회 상한(시방 기본: 200mL), 도징 워치독 절대 상한(시방 기본: 120초) | 3.2, 4.1 |
| 8 | 시간 동기 10분 실패 시 오프라인 운전 허용 여부 | 4.3 |
| 9 | 실내 온도/CO2 유효범위 수치 | 5.1 |
| 10 | 신규 코드 설치 경로 및 저장소 분리 여부 | 8.1 |
| 11 | 백업용 git 원격 저장소 주소/인증 | 5.3 |
| 12 | 라우터 포트포워딩 8300→8300 변경 가능 시점(컷오버 일정 연동) | 6.1 |
| 13 | USB 어댑터 물리 포트 고정(라벨링) 가능 여부 | 7.5 |
| 14 | sudoers의 usbreset NOPASSWD 항목 유지 | 7.6 |

## 부록 B. 참조 (현행 시스템 근거 위치)

- Node-RED 플로우: `/home/cja/.node-red/projects/cja-skyfarms/flows.json`
- Python 제어/센서: `/home/cja/Work/cja-skyfarms-project/{controllers,sensors}/`
- 카메라/ML: `/home/cja/Work/cja-skyfarms-project/camera/`
- DB: `/home/cja/Work/cja-skyfarms-project/data/data.db`
- 캘리브레이션 현행값: `sensors/Dist_2_EC_pH.py` (EC −0.3, pH +0.3)
- 도징 임계값 변경 이력 주석: `controllers/Dist_2_EC_pH_auto_control.py` ("20260304 JM edit 6.1 -> 5.9")
