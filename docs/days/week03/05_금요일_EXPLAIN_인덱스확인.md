# ORM이 뽑은 SQL은 정말 인덱스를 타고 있는가

1일 1CS / 3주차 금요일 / 통합 과제
코드: [`lab/week03_fri_index_explain_lab.py`](../../../lab/week03_fri_index_explain_lab.py)

이번 주와 지난주에 배운 것을 실제 실행 계획 위에서 확인한다.

| 주제 | 이 과제에서 확인하는 것 |
|---|---|
| 인덱스와 B-tree (2주차 수) | Seq Scan이 Index Scan으로 바뀌는 순간 |
| 시간복잡도 (1주차 목) | 데이터가 10배가 되면 시간이 어떻게 변하는가 |
| 정규화와 반정규화 (3주차 수) | 조인이 정말 병목인가 |
| 가상 메모리 (3주차 월) | 왜 디스크 읽기 횟수가 기준인가 |

---

## 준비

PostgreSQL 기준이다. Docker로 띄우면 기존 환경을 안 건드린다.

```bash
docker run -d --name cs-lab-pg \
  -e POSTGRES_PASSWORD=lab -e POSTGRES_DB=cslab \
  -p 5433:5432 postgres:16

psql -h localhost -p 5433 -U postgres -d cslab
```

---

## 1단계 — 테스트 데이터 만들기

```sql
CREATE TABLE device (
    id      SERIAL PRIMARY KEY,
    name    TEXT NOT NULL,
    status  TEXT NOT NULL
);

CREATE TABLE measurement (
    id          SERIAL PRIMARY KEY,
    device_id   INTEGER NOT NULL REFERENCES device(id),
    value       DOUBLE PRECISION NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

-- 장비 500대
INSERT INTO device (name, status)
SELECT 'device-' || i,
       CASE WHEN i % 10 = 0 THEN 'warning' ELSE 'normal' END
FROM generate_series(1, 500) AS i;

-- 측정 데이터 200만 건
INSERT INTO measurement (device_id, value, created_at)
SELECT (random() * 499 + 1)::int,
       random() * 100,
       NOW() - (random() * 90 || ' days')::interval
FROM generate_series(1, 2000000);

ANALYZE;
```

`ANALYZE`를 빼먹으면 옵티마이저가 옛 통계로 판단해서
인덱스가 있어도 안 쓰는 일이 생긴다. 데이터를 대량 넣은 뒤에는 항상 실행한다.

---

## 2단계 — 인덱스 없이 조회

```sql
EXPLAIN ANALYZE
SELECT * FROM measurement WHERE device_id = 42;
```

**읽는 법**

```
Seq Scan on measurement  (cost=0.00..40000.00 rows=4000 width=28)
                         (actual time=0.030..180.5 rows=4012 loops=1)
  Filter: (device_id = 42)
  Rows Removed by Filter: 1995988
Execution Time: 185.2 ms
```

| 항목 | 의미 |
|---|---|
| `Seq Scan` | 전체 스캔. 인덱스를 안 탔다 |
| `Rows Removed by Filter` | 읽었지만 버린 행 수. 이 숫자가 크면 낭비가 크다 |
| `rows=4000` vs `actual rows=4012` | 추정치와 실제. 크게 벌어지면 통계가 낡았다 |
| `Execution Time` | 실제 걸린 시간 |

**199만 건을 읽어서 4천 건만 남겼습니다.**
1주차 목요일에 배운 `O(n)`이 숫자로 나타난 것입니다.

기록:

| 항목 | 값 |
|---|---|
| 스캔 방식 | Seq Scan |
| Rows Removed by Filter | |
| Execution Time | |

---

## 3단계 — 인덱스를 걸고 다시

```sql
CREATE INDEX idx_measurement_device ON measurement (device_id);
ANALYZE measurement;

EXPLAIN ANALYZE
SELECT * FROM measurement WHERE device_id = 42;
```

이제 이렇게 바뀐다.

```
Bitmap Heap Scan on measurement (actual time=0.8..3.2 rows=4012 loops=1)
  Recheck Cond: (device_id = 42)
  ->  Bitmap Index Scan on idx_measurement_device (actual time=0.4..0.4 ...)
Execution Time: 4.1 ms
```

| 항목 | 인덱스 전 | 인덱스 후 |
|---|---|---|
| 스캔 방식 | Seq Scan | Bitmap Index Scan |
| Execution Time | | |
| 배수 | — | |

보통 **수십 배** 차이가 납니다.
2주차 수요일에 본 `O(n)` → `O(log n)`이 여기서 확인됩니다.

참고로 결과가 적으면 `Index Scan`, 많으면 `Bitmap Index Scan`이 나옵니다.
둘 다 인덱스를 탄 것입니다. 중요한 건 `Seq Scan`이 아니라는 점입니다.

---

## 4단계 — 인덱스를 못 타게 만들어 보기

2주차 수요일 함정 1을 직접 재현한다.

```sql
CREATE INDEX idx_measurement_created ON measurement (created_at);
ANALYZE measurement;

-- 컬럼에 함수를 씌운 경우
EXPLAIN ANALYZE
SELECT * FROM measurement WHERE DATE(created_at) = '2026-08-01';

-- 컬럼을 그대로 두고 범위로 바꾼 경우
EXPLAIN ANALYZE
SELECT * FROM measurement
WHERE created_at >= '2026-08-01' AND created_at < '2026-08-02';
```

**같은 결과를 내는 두 쿼리인데 실행 계획이 완전히 다릅니다.**

| 쿼리 | 스캔 방식 | Execution Time |
|---|---|---|
| `DATE(created_at) = ...` | Seq Scan | |
| `created_at >= ... AND < ...` | Index Scan | |

인덱스는 `created_at`의 값으로 정렬되어 있지 `DATE(created_at)`으로 정렬된 게 아닙니다.
컬럼을 가공하는 순간 정렬 순서가 무의미해집니다.

**원칙: 왼쪽(컬럼)은 건드리지 말고 오른쪽(값)을 바꾼다.**

---

## 5단계 — 복합 인덱스의 컬럼 순서

```sql
DROP INDEX idx_measurement_device;
CREATE INDEX idx_dev_created ON measurement (device_id, created_at);
ANALYZE measurement;

-- (1) 첫 컬럼부터 시작
EXPLAIN ANALYZE SELECT * FROM measurement WHERE device_id = 42;

-- (2) 두 컬럼 다 사용
EXPLAIN ANALYZE SELECT * FROM measurement
WHERE device_id = 42 AND created_at > NOW() - INTERVAL '7 days';

-- (3) 첫 컬럼을 건너뜀
EXPLAIN ANALYZE SELECT * FROM measurement
WHERE created_at > NOW() - INTERVAL '7 days';
```

| 쿼리 | 인덱스 사용 여부 | 이유 |
|---|---|---|
| (1) | | |
| (2) | | |
| (3) | | |

(3)만 `Seq Scan`이 나옵니다. **왼쪽 접두사 규칙**입니다.
전화번호부가 (성, 이름) 순인데 이름만 알고 찾으려는 것과 같습니다.

---

## 6단계 — 조인이 정말 병목인가

3주차 수요일의 판단 기준을 확인한다.

```sql
EXPLAIN ANALYZE
SELECT m.value, d.name
FROM measurement m
JOIN device d ON m.device_id = d.id
WHERE m.device_id = 42;
```

실행 계획에서 각 노드의 `actual time`을 본다.

```
Nested Loop (actual time=0.5..5.1 rows=4012)
  ->  Bitmap Heap Scan on measurement (actual time=0.4..3.8 ...)   <- 여기가 대부분
  ->  Index Scan on device (actual time=0.001..0.001 ...)          <- 여기는 거의 0
```

**전체 시간의 대부분이 조인이 아니라 스캔에 쓰입니다.**

이게 3주차 수요일에서 말한 "반정규화 전에 확인할 것"입니다.
조인이 느려 보여도 실제로는 스캔이 병목인 경우가 대부분이고,
그렇다면 답은 반정규화가 아니라 인덱스입니다.

---

## 7단계 — Django ORM이 실제로 뽑는 SQL

```python
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext

# 실제 나가는 SQL 확인
qs = Measurement.objects.filter(device_id=42)
print(qs.query)

# N+1 여부 확인 (1주차 목요일 함정 3)
with CaptureQueriesContext(connection) as ctx:
    for m in Measurement.objects.all()[:100]:
        _ = m.device.name
print("쿼리 수:", len(ctx))          # 101이 나오면 N+1

with CaptureQueriesContext(connection) as ctx:
    for m in Measurement.objects.select_related("device")[:100]:
        _ = m.device.name
print("쿼리 수:", len(ctx))          # 1이 나와야 정상
```

`settings.py`에 이걸 켜두면 실행 계획도 함께 볼 수 있다.

```python
# 개발 환경에서만
LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django.db.backends": {"handlers": ["console"], "level": "DEBUG"},
    },
}
```

---

## 8단계 — 안 쓰이는 인덱스 찾기

```sql
SELECT relname AS table_name,
       indexrelname AS index_name,
       idx_scan AS times_used,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC;
```

`times_used`가 0인 인덱스는 **한 번도 안 쓰인 인덱스**입니다.
쓰기 비용과 저장 공간만 내고 아무것도 돌려주지 않고 있습니다.

2주차 수요일 함정 2가 실제 운영에서 어떻게 드러나는지 보여주는 지표입니다.

---

## 정리

다음 세 가지를 자기 말로 설명할 수 있으면 이번 과제는 끝난다.

1. `EXPLAIN` 결과에서 무엇을 먼저 보는가
2. 인덱스를 걸었는데 안 타는 경우가 왜 생기는가 (최소 두 가지)
3. 느린 쿼리를 만났을 때 어떤 순서로 손대는가

3번의 답:

```
1. EXPLAIN ANALYZE로 실제 병목 확인
2. 인덱스 추가 / 쿼리 수정 (함수 제거, 컬럼 순서) / N+1 제거
3. 그래도 느리면 캐시 (Redis)
4. 그래도 안 되면 반정규화
```

반정규화가 마지막인 이유는 **되돌리기가 가장 어렵기 때문**입니다.

---

## 실무로 옮길 것

- [ ] 지금 가장 느린 API의 쿼리에 `EXPLAIN ANALYZE`를 실행해 봤는가
- [ ] `pg_stat_user_indexes`에서 `idx_scan = 0`인 인덱스가 있는가
- [ ] ORM에서 `__date`, `__year` 같은 룩업을 쓰는 곳이 있는가 (함수 씌우기)
- [ ] `select_related` / `prefetch_related`가 빠진 반복문이 있는가

---

## 정리

```bash
docker rm -f cs-lab-pg
```
