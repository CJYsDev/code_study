# 트랜잭션과 ACID — 왜 필요하고 무엇을 보장하는가

1일 1CS / 1주차 수요일 / 데이터베이스
티어: C (7섹션 전부)

---

## 한 줄 요약

트랜잭션은 여러 개의 DB 작업을 **하나의 성공/실패 단위로 묶어서**,
"중간까지만 반영된 상태"가 데이터에 영구히 남지 않게 하는 장치입니다.

---

## 이게 없으면 생기는 문제

### 문제 1 — 중간에 끊긴 상태가 남는다

센서 임계값 초과 알림을 처리한다고 해봅시다. 해야 할 일이 세 개입니다.

```
1. alert 테이블에 알림 레코드 INSERT
2. device 테이블의 상태를 'warning'으로 UPDATE
3. notification_log에 발송 이력 INSERT
```

1번이 끝나고 2번을 하는 도중에 서버가 죽거나 예외가 터졌습니다.
결과는 이렇습니다.

- alert 테이블: 경고가 발생했다고 기록됨
- device 테이블: 아직 'normal'

**이 상태는 영원히 남습니다.** 아무도 고쳐주지 않습니다.
운영자 화면에서는 장비가 정상인데 알림 목록에는 경고가 떠 있습니다.
나중에 이런 게 수천 건 쌓이면, 어느 쪽이 진실인지 판단할 근거조차 없어집니다.
그래서 데이터 정합성을 맞추는 배치 스크립트를 따로 짜게 되고,
그 스크립트가 또 중간에 죽으면서 문제가 반복됩니다.

### 문제 2 — 동시에 실행되면 서로를 덮어쓴다

두 요청이 같은 장비의 알림 카운트를 동시에 올립니다.

```
요청 A: count 읽음 (5)
요청 B: count 읽음 (5)
요청 A: 5 + 1 = 6 저장
요청 B: 5 + 1 = 6 저장     <- A가 한 일이 사라짐
```

두 번 올렸는데 결과는 한 번 올라간 것과 같습니다. lost update라고 부릅니다.
월요일에 본 스레드의 race condition과 **정확히 같은 문제**입니다.
다만 무대가 메모리가 아니라 디스크일 뿐입니다.

트랜잭션은 이 두 가지를 동시에 해결합니다.

---

## 비유

**이사입니다.**

짐을 옮기는 도중에 트럭이 고장 나면, 짐이 옛집과 새집에 반씩 나뉩니다.
이 상태가 제일 나쁩니다. 옛집으로 돌아갈 수도 없고 새집에서 살 수도 없습니다.

트랜잭션은 이렇게 합니다.
짐을 다 옮기기 전까지는 **"이사 완료" 도장을 찍지 않고**,
문제가 생기면 옮기던 짐을 전부 옛집에 되돌려 놓습니다.
바깥에서 보면 이사는 "완전히 됐거나" "아예 안 됐거나" 둘 중 하나입니다.

단, 이 비유가 맞지 않는 부분: 실제 이사는 되돌리는 데 다시 시간과 비용이 들지만,
DB는 미리 적어둔 로그를 되짚기 때문에 되돌리는 비용이 훨씬 쌉니다.
그래서 "일단 시도하고 안 되면 롤백"이라는 전략이 성립합니다.

---

## 실제로 어떻게 동작하는가

### ACID 네 글자

| 글자 | 이름 | 보장하는 것 | 어떻게 구현하나 |
|---|---|---|---|
| A | Atomicity (원자성) | 전부 되거나 전부 안 되거나 | undo log — 변경 전 값을 기록해뒀다가 되돌림 |
| C | Consistency (일관성) | 규칙을 깨는 상태로 끝나지 않음 | 제약조건(PK, FK, CHECK, NOT NULL) |
| I | Isolation (격리성) | 동시 트랜잭션이 서로를 방해하지 않음 | 락 또는 MVCC |
| D | Durability (지속성) | 커밋했으면 서버가 죽어도 살아남음 | WAL(Write-Ahead Log) + fsync |

네 개를 나란히 외우기보다, **A와 D는 "혼자 있을 때"의 보장이고,
I는 "여럿이 있을 때"의 보장**이라고 나누면 정리가 됩니다.
C는 사실 나머지 셋과 성격이 좀 다릅니다. 뒤에서 다시 언급합니다.

### Durability는 어떻게 가능한가 — WAL

커밋했다고 응답했는데 그 직후 서버가 꺼지면 데이터가 날아가지 않을까요?
DB는 이렇게 막습니다.

```
1. 변경 내용을 로그 파일에 먼저 순차 기록한다  (WAL)
2. 로그가 디스크에 확실히 쓰였는지 확인한다     (fsync)
3. 그제서야 클라이언트에게 "커밋 완료"라고 답한다
4. 실제 데이터 파일 반영은 나중에 천천히 한다
```

핵심은 **순서**입니다. 데이터 파일보다 로그를 먼저 씁니다.
서버가 죽어도 로그가 남아 있으므로, 재시작할 때 로그를 다시 읽어 복구합니다.

로그를 먼저 쓰는 이유는 성능 때문이기도 합니다.
데이터 파일 수정은 디스크 여기저기를 건드리는 랜덤 쓰기지만,
로그는 파일 끝에 이어 붙이는 순차 쓰기라 훨씬 빠릅니다.

### 코드에서는 어떻게 쓰나

**Django**

```python
from django.db import transaction

@transaction.atomic
def handle_alert(device_id):
    alert = Alert.objects.create(device_id=device_id, level="warning")
    Device.objects.filter(id=device_id).update(status="warning")
    NotificationLog.objects.create(alert=alert)
    # 예외가 나면 이 블록에서 한 일이 전부 취소된다
```

**FastAPI + SQLAlchemy**

```python
def handle_alert(db: Session, device_id: int):
    try:
        db.add(Alert(device_id=device_id, level="warning"))
        db.query(Device).filter_by(id=device_id).update({"status": "warning"})
        db.commit()
    except Exception:
        db.rollback()
        raise
```

두 코드가 하는 일은 같습니다. Django는 데코레이터가 커밋/롤백을 대신 처리해 줄 뿐입니다.

---

## 주니어가 자주 빠지는 함정

### 함정 1 — 트랜잭션을 건 줄 알았는데 안 걸려 있다

Django는 기본이 **autocommit**입니다. `save()` 한 번이 곧 커밋 한 번입니다.

```python
# 흔한 실수 - 세 줄이 각각 별개의 트랜잭션이다
def handle_alert(device_id):
    alert = Alert.objects.create(...)           # 여기서 커밋
    Device.objects.filter(...).update(...)      # 여기서 또 커밋
    NotificationLog.objects.create(...)         # 여기서 또 커밋
    # 두 번째에서 터지면 첫 번째는 이미 남아 있다

# 권장 - 명시적으로 하나로 묶는다
with transaction.atomic():
    alert = Alert.objects.create(...)
    Device.objects.filter(...).update(...)
    NotificationLog.objects.create(...)
```

"DB를 쓰니까 알아서 안전하겠지"가 가장 흔한 오해입니다.
**묶어달라고 말하지 않으면 묶이지 않습니다.**

### 함정 2 — 트랜잭션 안에서 외부 호출을 한다

```python
# 흔한 실수
with transaction.atomic():
    alert = Alert.objects.create(...)
    send_slack_message(alert)     # 외부 API. 느리고, 롤백해도 안 돌아온다

# 권장 - 커밋이 확정된 뒤에 실행되도록 예약한다
with transaction.atomic():
    alert = Alert.objects.create(...)
    transaction.on_commit(lambda: send_slack_message(alert))
```

두 가지가 동시에 잘못됩니다.

- 외부 API가 3초 걸리면 그동안 **DB 락을 3초간 붙잡고 있습니다.** 동시성이 무너집니다.
- 슬랙 메시지는 이미 나갔는데 그 뒤에 롤백되면, **없는 알림에 대한 메시지**가 발송됩니다.

트랜잭션 안에는 DB 작업만 둡니다. 이메일, 파일 업로드, 결제 요청, HTTP 호출은 전부 밖으로 뺍니다.

### 함정 3 — 예외를 삼켜서 롤백이 사라진다

```python
# 흔한 실수 - atomic 블록 안에서 예외를 잡으면 롤백 신호가 사라진다
with transaction.atomic():
    try:
        Device.objects.filter(...).update(...)
    except Exception:
        pass          # 실패했는데 트랜잭션은 그대로 커밋된다

# 권장 - 롤백이 필요하면 예외를 밖으로 내보낸다
try:
    with transaction.atomic():
        Device.objects.filter(...).update(...)
except Exception:
    logger.exception("장비 상태 갱신 실패")
```

`atomic` 블록은 **예외가 밖으로 나가는지**를 보고 롤백 여부를 정합니다.
안에서 잡아버리면 "아무 문제 없었다"고 판단합니다.
try/except를 쓰려면 atomic 블록 바깥에 둡니다.

### 함정 4 — 트랜잭션 범위를 너무 넓게 잡는다

```python
# 흔한 실수 - 요청 전체를 하나의 트랜잭션으로 감싼다
# settings.py
DATABASES = {"default": {..., "ATOMIC_REQUESTS": True}}
```

편해 보이지만, 응답을 만들어 렌더링하는 동안까지 DB 커넥션과 락을 붙잡습니다.
동시 접속이 늘면 커넥션 풀이 먼저 고갈됩니다.

트랜잭션은 **짧을수록 좋습니다.** 정합성이 실제로 필요한 몇 줄만 감쌉니다.
읽기만 하는 조회 API에는 트랜잭션이 필요 없습니다.

---

## 트레이드오프

```
트랜잭션을 쓰면
  얻는 것: 데이터 정합성, 실패 복구가 자동, 동시성 문제를 DB에 위임
  잃는 것: 락 대기로 인한 동시 처리량 감소, 로그 기록에 따른 쓰기 비용,
           커넥션 점유 시간 증가
  손해인 상황: 대량 로그/메트릭 적재 (한 건 유실이 치명적이지 않고 처리량이 중요),
              이미 확정된 이벤트를 그냥 append만 하는 경우
```

한 가지 짚어둘 점. **ACID의 C는 나머지 셋과 성격이 다릅니다.**
A, I, D는 DB가 알아서 보장하지만, C는 상당 부분이 **개발자 책임**입니다.
"잔액은 음수가 될 수 없다" 같은 규칙은 DB가 스스로 알지 못합니다.
CHECK 제약조건이나 애플리케이션 로직으로 알려줘야 지켜집니다.
"트랜잭션을 걸었으니 일관성은 보장된다"는 말은 절반만 맞습니다.

또 하나. Isolation은 **켜고 끄는 스위치가 아니라 단계**입니다.
격리를 강하게 할수록 안전해지지만 동시성이 떨어집니다.
그 단계를 고르는 게 4주차 수요일의 "격리수준과 락" 주제입니다.

---

## 연결되는 CS 지식

- **격리수준과 락** — Isolation을 어느 강도로 살 것인지 고르는 문제입니다. dirty read, non-repeatable read, phantom read가 여기서 나옵니다. (4주차 수요일 주제)
- **임계 구역과 상호 배제** — 월요일에 본 스레드 동기화 문제가 디스크 위에서 재현된 것이 트랜잭션 격리입니다. 같은 문제, 다른 무대입니다.
- **WAL과 디스크 I/O 비용** — 순차 쓰기가 랜덤 쓰기보다 왜 압도적으로 싼지 알면, 로그를 먼저 쓰는 설계가 자연스럽게 이해됩니다. 목요일의 시간복잡도, 3주차의 인덱스와도 이어집니다.
- **분산 트랜잭션(2PC)과 Saga 패턴** — 서비스가 여러 개로 쪼개지면 ACID를 그대로 쓸 수 없습니다. 무엇을 포기하는지 보는 것이 그다음 단계입니다.

---

## 다음 행동

psql 터미널을 두 개 열고 양쪽에서 `BEGIN;`을 친 뒤,
같은 행을 동시에 UPDATE 해보면 한쪽이 멈춰 서는 것을 직접 볼 수 있습니다.
락이 실제로 존재한다는 걸 체감하는 데 5분이면 충분합니다.
