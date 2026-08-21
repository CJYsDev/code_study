"""
1일 1CS / 3주차 금요일 통합 실험

인덱스는 정말 효과가 있는가, 그리고 언제 안 타는가

확인하는 것
  [1] 인덱스 없이 조회하면 전체를 훑는다                (2주차 수)
  [2] 인덱스를 걸면 실행계획과 시간이 바뀐다            (2주차 수)
  [3] 컬럼에 함수를 씌우면 인덱스를 못 탄다            (2주차 수 - 함정 1)
  [4] 복합 인덱스는 컬럼 순서가 전부다                 (2주차 수 - 왼쪽 접두사)
  [5] 카디널리티가 낮으면 인덱스를 만들어도 무시된다   (2주차 수 - 함정 3)
  [6] 데이터가 10배가 되면 시간이 어떻게 변하는가      (1주차 목 - Big-O)
  [7] 인덱스는 읽기를 사고 쓰기를 판다                 (2주차 수 - 트레이드오프)

실행
  python lab/week03_fri_index_explain_lab.py

의존성 없음. 표준 라이브러리 sqlite3만 사용. 메모리 DB라 파일도 안 남는다.

PostgreSQL과의 대응
  sqlite  EXPLAIN QUERY PLAN     ->  postgres  EXPLAIN ANALYZE
  sqlite  SCAN <table>           ->  postgres  Seq Scan     (인덱스 못 탐)
  sqlite  SEARCH ... USING INDEX ->  postgres  Index Scan   (인덱스 탐)

주의
  이 스크립트는 검증되지 않은 상태다.
  '판정' 결과와 '평균시간'이 서로 어긋나 보이는 칸이 나올 수 있다.
  그 칸을 찾아내고 이유를 설명하는 것이 이번 과제의 핵심이다.
  아래 '관찰 기록지'를 먼저 열어두고 시작할 것.
"""

import random
import sqlite3
import time

LINE = "-" * 66
ROWS = 300_000


def header(title: str) -> None:
    print(f"\n{LINE}\n {title}\n{LINE}")


# ---------------------------------------------------------------


def build_db(rows: int = ROWS) -> sqlite3.Connection:
    """장비 500대, 측정 데이터 rows건을 가진 메모리 DB를 만든다."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE device (
            id     INTEGER PRIMARY KEY,
            name   TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE measurement (
            id         INTEGER PRIMARY KEY,
            device_id  INTEGER NOT NULL,
            value      REAL NOT NULL,
            status     TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    conn.executemany(
        "INSERT INTO device (id, name, status) VALUES (?, ?, ?)",
        [
            (i, f"device-{i}", "warning" if i % 10 == 0 else "normal")
            for i in range(1, 501)
        ],
    )

    rnd = random.Random(42)
    rows_data = []
    for i in range(rows):
        day = 1 + (i * 90) // rows  # 90일치로 고르게 분포
        rows_data.append(
            (
                rnd.randint(1, 500),
                rnd.random() * 100,
                "warning" if rnd.random() < 0.1 else "normal",
                f"2026-06-{day:02d}" if day <= 30 else f"2026-07-{day - 30:02d}",
            )
        )
    conn.executemany(
        "INSERT INTO measurement (device_id, value, status, created_at) "
        "VALUES (?, ?, ?, ?)",
        rows_data,
    )
    conn.commit()
    conn.execute("ANALYZE")
    return conn


def plan(conn: sqlite3.Connection, sql: str, params=()) -> str:
    """실행계획을 한 줄로 요약한다."""
    rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    return " / ".join(r[-1].strip() for r in rows)


def timed(conn: sqlite3.Connection, sql: str, params=(), repeat: int = 20) -> float:
    """평균 실행 시간(ms)."""
    start = time.perf_counter()
    for _ in range(repeat):
        conn.execute(sql, params).fetchall()
    return (time.perf_counter() - start) / repeat * 1000


def verdict(plan_text: str) -> str:
    """실행계획 문자열에 인덱스 이름이 있으면 인덱스를 탄 것으로 본다."""
    return "인덱스 사용" if "USING INDEX" in plan_text.upper() else "전체 스캔"


def report(conn, label: str, sql: str, params=()) -> tuple:
    p = plan(conn, sql, params)
    ms = timed(conn, sql, params)
    print(f"  {label}")
    print(f"    실행계획 : {p}")
    print(f"    판정     : {verdict(p)}")
    print(f"    평균시간 : {ms:.3f} ms\n")
    return p, ms


# ---------------------------------------------------------------


def step1_2_index_effect(conn) -> None:
    header("[1][2] 인덱스 전후 비교")

    sql = "SELECT * FROM measurement WHERE device_id = 42"

    print(" 인덱스 없음:")
    _, before = report(conn, "device_id = 42", sql)

    conn.execute("CREATE INDEX idx_dev ON measurement (device_id)")
    conn.execute("ANALYZE")

    print(" 인덱스 생성 후:")
    _, after = report(conn, "device_id = 42", sql)

    print(f"    -> {before / after:.1f}배 차이\n")


def step3_function_kills_index(conn) -> None:
    header("[3] 컬럼에 함수를 씌우면 인덱스를 못 탄다")

    conn.execute("CREATE INDEX idx_created ON measurement (created_at)")
    conn.execute("ANALYZE")

    print(" 컬럼을 가공한 경우:")
    report(
        conn,
        "substr(created_at, 1, 7) = '2026-06'",
        "SELECT * FROM measurement WHERE substr(created_at, 1, 7) = ?",
        ("2026-06",),
    )

    print(" 컬럼을 그대로 두고 범위로 바꾼 경우:")
    report(
        conn,
        "created_at >= '2026-06-01' AND < '2026-07-01'",
        "SELECT * FROM measurement WHERE created_at >= ? AND created_at < ?",
        ("2026-06-01", "2026-07-01"),
    )

    print(
        """    원칙: 왼쪽(컬럼)은 건드리지 말고 오른쪽(값)을 바꾼다.

    Django에서 같은 실수
      .filter(created_at__date=d)                   -> 함수가 씌워진다
      .filter(created_at__gte=s, created_at__lt=e)  -> 인덱스를 탄다"""
    )


def step4_composite_order(conn) -> None:
    header("[4] 복합 인덱스는 컬럼 순서가 전부다")

    conn.execute("DROP INDEX idx_dev")
    conn.execute("DROP INDEX idx_created")
    conn.execute("CREATE INDEX idx_dev_created ON measurement (device_id, created_at)")
    conn.execute("ANALYZE")

    print(" 인덱스: (device_id, created_at)\n")

    report(
        conn,
        "(1) device_id = 42                     -- 첫 컬럼부터",
        "SELECT * FROM measurement WHERE device_id = ?",
        (42,),
    )
    report(
        conn,
        "(2) device_id = 42 AND created_at > ?  -- 순서대로 둘 다",
        "SELECT * FROM measurement WHERE device_id = ? AND created_at > ?",
        (42, "2026-07-01"),
    )
    report(
        conn,
        "(3) created_at > ?                     -- 첫 컬럼을 건너뜀",
        "SELECT * FROM measurement WHERE created_at > ?",
        ("2026-07-01",),
    )

    print(
        """    왼쪽 접두사 규칙.
    전화번호부가 (성, 이름) 순으로 정렬되어 있으면
    '김'씨는 쉽게 찾지만 이름이 '철수'인 사람은 전부 뒤져야 하는 것과 같다."""
    )


def step5_low_cardinality(conn) -> None:
    header("[5] 값의 종류가 적으면 인덱스가 무시된다")

    conn.execute("CREATE INDEX idx_status ON measurement (status)")
    conn.execute("ANALYZE")

    total = conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0]
    normal = conn.execute(
        "SELECT COUNT(*) FROM measurement WHERE status = 'normal'"
    ).fetchone()[0]

    print(
        f"    status 분포: normal {normal:,} / 전체 {total:,} "
        f"({normal / total * 100:.0f}%)\n"
    )

    report(
        conn,
        "status = 'normal'   (전체의 약 90%)",
        "SELECT * FROM measurement WHERE status = ?",
        ("normal",),
    )
    report(
        conn,
        "status = 'warning'  (전체의 약 10%)",
        "SELECT * FROM measurement WHERE status = ?",
        ("warning",),
    )

    print(
        """    값의 종류가 많은 컬럼일수록(device_id, email, created_at) 인덱스 효과가 크다."""
    )
    conn.execute("DROP INDEX idx_status")


def step6_scaling() -> None:
    header("[6] 데이터가 늘어나면 시간이 어떻게 변하는가")

    print(f" {'행 수':>10} | {'인덱스 없음(ms)':>16} | {'인덱스 있음(ms)':>16}")
    print(f" {'-' * 10}-+-{'-' * 16}-+-{'-' * 16}")

    sql = "SELECT * FROM measurement WHERE device_id = 42"
    for rows in (30_000, 150_000, 600_000):
        c = build_db(rows)
        without = timed(c, sql, repeat=10)
        c.execute("CREATE INDEX idx_dev ON measurement (device_id)")
        c.execute("ANALYZE")
        with_idx = timed(c, sql, repeat=10)
        print(f" {rows:>10,} | {without:>16.3f} | {with_idx:>16.3f}")
        c.close()


def step7_write_cost() -> None:
    header("[7] 인덱스는 읽기를 사고 쓰기를 판다")

    rnd = random.Random(1)
    batch = [
        (rnd.randint(1, 500), rnd.random() * 100, "normal", "2026-08-01")
        for _ in range(50_000)
    ]
    insert = (
        "INSERT INTO measurement (device_id, value, status, created_at) "
        "VALUES (?, ?, ?, ?)"
    )

    print(f" {'인덱스 개수':>12} | {'5만건 INSERT(초)':>18}")
    print(f" {'-' * 12}-+-{'-' * 18}")

    for n_idx in (0, 1, 3):
        c = build_db(50_000)
        for i, cols in enumerate(
            ["(device_id)", "(created_at)", "(status, value)"][:n_idx]
        ):
            c.execute(f"CREATE INDEX idx_{i} ON measurement {cols}")
        c.commit()

        start = time.perf_counter()
        c.executemany(insert, batch)
        c.commit()
        elapsed = time.perf_counter() - start

        print(f" {n_idx:>12} | {elapsed:>18.3f}")
        c.close()

    print(
        """
    운영 DB에서 안 쓰이는 인덱스 찾기 (PostgreSQL)
      SELECT relname, indexrelname, idx_scan
      FROM pg_stat_user_indexes ORDER BY idx_scan ASC;"""
    )


# ---------------------------------------------------------------


def main() -> None:
    print("=" * 66)
    print(" 3주차 금요일 통합 실험 - 인덱스와 실행계획")
    print(f" 테스트 데이터: 장비 500대 / 측정 {ROWS:,}건 (메모리 DB)")
    print("=" * 66)

    conn = build_db()
    step1_2_index_effect(conn)
    step3_function_kills_index(conn)
    step4_composite_order(conn)
    step5_low_cardinality(conn)
    conn.close()

    step6_scaling()
    step7_write_cost()


if __name__ == "__main__":
    main()


# ===============================================================
# 관찰 기록지
# ===============================================================
#
# 돌려보고 직접 채울 것.
# '판정'과 '평균시간'이 어긋나는 칸이 이번 과제의 핵심이다.
#
# [1][2] 인덱스 전후
#     인덱스 없음 : ______ ms   실행계획 : ____________
#     인덱스 있음 : ______ ms   실행계획 : ____________
#     몇 배 차이  : ______
#
# [3] 함수를 씌운 경우
#     substr(...) = ?            : ______ ms   판정 : ________
#     created_at >= ? AND < ?    : ______ ms   판정 : ________
#     -> 판정은 다른데 시간 차이는 얼마나 나는가?
#        차이가 기대만큼 안 났다면 왜인가?
#        (힌트: 두 쿼리가 각각 몇 건을 돌려주는지 세어볼 것.
#               조회 범위를 하루로 좁히면 어떻게 달라지는가?)
#
# [4] 복합 인덱스 (device_id, created_at)
#     (1) device_id = ?               : ______ ms   판정 : ________
#     (2) device_id = ? AND created_at > ? : ______ ms   판정 : ________
#     (3) created_at > ?              : ______ ms   판정 : ________
#     -> (3)의 판정이 '인덱스 사용'으로 나왔는가?
#        그렇다면 시간은 왜 (1)(2)보다 훨씬 긴가?
#        (3)의 실행계획 문자열을 그대로 옮겨 적어볼 것 : ____________
#        (1)과 다른 부분이 있다. 그게 무엇을 의미하는가?
#        -> 이 스크립트의 verdict() 함수는 무엇을 놓치고 있는가?
#           고친다면 어떻게 고칠 것인가?
#
# [5] 카디널리티
#     status = 'normal'  : ______ ms   판정 : ________
#     status = 'warning' : ______ ms   판정 : ________
#     -> 둘의 판정이 다르게 나왔는가? 왜 그런가?
#
# [6] 데이터 증가
#     행 수를 20배로 늘렸을 때
#       인덱스 없음의 시간은 몇 배가 되었는가 : ______
#       인덱스 있음의 시간은 몇 배가 되었는가 : ______
#     -> 각각 O(?) 인가?
#
# [7] 쓰기 비용
#     인덱스 0개 : ______ 초
#     인덱스 1개 : ______ 초
#     인덱스 3개 : ______ 초
#     -> 늘어나는 비율이 인덱스 개수에 비례하는가?
#
# 정리 질문
#   1. EXPLAIN 결과에서 무엇을 먼저 보는가
#   2. 인덱스를 걸었는데 안 타는 경우는 왜 생기는가 (최소 세 가지)
#   3. '실행계획에 인덱스 이름이 있다'와 '인덱스가 효과가 있다'는 같은 말인가
#   4. 느린 쿼리를 만나면 어떤 순서로 손대는가
