"""
1일 1CS / 1주차 금요일 통합 실험

요청 한 건은 어느 프로세스, 어느 스레드가 처리하는가

확인하는 것
  [1] 실행 주체 - 스레드는 PID가 같고 프로세스는 PID가 다르다   (1주차 월)
  [2] 전역 변수 - 프로세스가 나뉘면 상태가 공유되지 않는다      (1주차 월)
  [3] 공용 저장소 - 프로세스 밖에 두면 다시 합쳐진다 (Redis 역할)
  [4] GIL      - IO는 스레드로, CPU는 프로세스로                (1주차 월)
  [5] 경합     - 여러 스레드가 같은 값을 건드리면 유실된다      (1주차 수)

실행
  python lab/week01_fri_process_thread_lab.py

의존성 없음. 표준 라이브러리만 사용.

주의
  이 스크립트는 검증되지 않은 상태다.
  출력이 주석의 설명과 어긋나는 지점이 있을 수 있고, 그것을 찾는 것이 과제다.
  아래 '관찰 기록지'를 먼저 열어두고 시작할 것.
"""

import multiprocessing as mp
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

# ---------------------------------------------------------------
# 공통
# ---------------------------------------------------------------

LINE = "-" * 62


def header(title: str) -> None:
    print(f"\n{LINE}\n {title}\n{LINE}")


def identity(label: str) -> str:
    """지금 이 코드를 실행 중인 주체를 문자열로 돌려준다."""
    return (
        f"  {label:<12} PID={os.getpid():<8} "
        f"TID={threading.get_ident():<20} "
        f"name={threading.current_thread().name}"
    )


# ---------------------------------------------------------------
# [1] 실행 주체 확인
# ---------------------------------------------------------------


def step1_identity() -> None:
    header("[1] 누가 이 일을 처리하는가")

    print(" 메인 스레드에서 직접:")
    print(identity("main"))

    print("\n 스레드 4개:")
    with ThreadPoolExecutor(max_workers=4) as ex:
        for line in ex.map(identity, [f"thread-{i}" for i in range(4)]):
            print(line)

    print("\n 프로세스 4개:")
    with ProcessPoolExecutor(max_workers=4) as ex:
        for line in ex.map(identity, [f"process-{i}" for i in range(4)]):
            print(line)

    print(
        """
 웹 서버로 옮기면
   gunicorn --workers 4             -> 위의 '프로세스 4개'와 같은 그림
   gunicorn --workers 2 --threads 4 -> 두 그림이 겹쳐 쌓인 형태
"""
    )


# ---------------------------------------------------------------
# [2] 전역 변수는 프로세스 간에 공유되지 않는다
# ---------------------------------------------------------------

counter = 0


def bump_global(_: int) -> tuple:
    """모듈 전역 변수를 1 올리고 (PID, 현재값)을 돌려준다."""
    global counter
    counter += 1
    return os.getpid(), counter


def step2_global_state() -> None:
    header("[2] 전역 변수는 프로세스 경계를 넘지 못한다")

    print(" 스레드 4개로 12번 호출:")
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(bump_global, range(12)))
    print(f"   최종값들: {[v for _, v in results]}")
    print(f"   서로 다른 PID 개수: {len({p for p, _ in results})}")

    print("\n 프로세스 4개로 12번 호출:")
    with ProcessPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(bump_global, range(12)))
    print(f"   최종값들: {[v for _, v in results]}")
    print(f"   서로 다른 PID 개수: {len({p for p, _ in results})}")

    print(
        """
 실무에서 이렇게 터진다
   - 인메모리 캐시가 워커 수만큼 쪼개짐
   - 로그인 세션이 요청마다 있었다 없었다 함
   - APScheduler가 워커 수만큼 중복 실행됨
   - 로컬 runserver(단일 프로세스)에서는 절대 재현되지 않음
"""
    )


# ---------------------------------------------------------------
# [3] 프로세스 밖의 공용 저장소를 쓰면 해결된다
# ---------------------------------------------------------------


def bump_shared(args) -> tuple:
    shared, lock = args
    with lock:
        shared.value += 1
        return os.getpid(), shared.value


def step3_shared_store() -> None:
    header("[3] 공용 저장소에 두면 다시 합쳐진다")

    manager = mp.Manager()
    shared = manager.Value("i", 0)
    lock = manager.Lock()

    with ProcessPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(bump_shared, [(shared, lock)] * 12))

    print(f"   최종값들: {[v for _, v in results]}")
    print(f"   서로 다른 PID 개수: {len({p for p, _ in results})}")
    print(
        """
 상태가 프로세스 '밖'에 있으면 워커가 여러 개여도 하나의 값을 본다.

 여기서 Redis가 왜 필요한지가 답해진다
   빠른 캐시라서가 아니라, 워커 여러 개가 함께 볼 수 있는 자리라서.

 (Manager는 실습용이다. 실제로는 Redis나 DB를 쓴다.)
"""
    )


# ---------------------------------------------------------------
# [4] GIL - IO는 스레드로, CPU는 프로세스로
# ---------------------------------------------------------------


def cpu_work(n: int = 4_000_000) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total


def io_work(seconds: float = 0.4) -> None:
    time.sleep(seconds)


def io_wrapper(_) -> None:
    io_work()


def cpu_wrapper(_) -> int:
    return cpu_work()


def bench(title: str, executor_cls, task, jobs: int) -> None:
    print(f"\n {title}")
    print(f" {'워커':>6} | {'시간(초)':>10} | {'배속':>8}")
    print(f" {'-' * 6}-+-{'-' * 10}-+-{'-' * 8}")

    baseline = None
    for workers in (1, 2, 4, 8):
        start = time.perf_counter()
        with executor_cls(max_workers=workers) as ex:
            list(ex.map(task, range(jobs)))
        elapsed = time.perf_counter() - start
        if baseline is None:
            baseline = elapsed
        print(f" {workers:>6} | {elapsed:>10.3f} | {baseline / elapsed:>7.2f}x")


def step4_gil() -> None:
    cores = os.cpu_count()
    header(f"[4] GIL - IO와 CPU는 다르게 움직인다  (코어 {cores}개)")

    bench("IO 작업 + 스레드", ThreadPoolExecutor, io_wrapper, 8)
    bench("CPU 작업 + 스레드", ThreadPoolExecutor, cpu_wrapper, 8)
    bench("CPU 작업 + 프로세스", ProcessPoolExecutor, cpu_wrapper, 8)

    print(
        """
 위 세 표를 나란히 놓고 볼 것.
 어느 표에서 배속이 오르고 어느 표에서 오르지 않는가.
 그 차이를 만드는 것이 무엇인가.
"""
    )


# ---------------------------------------------------------------
# [5] 스레드 경합
# ---------------------------------------------------------------

unsafe_total = 0
safe_total = 0
safe_lock = threading.Lock()


def unsafe_add() -> None:
    global unsafe_total
    for _ in range(100_000):
        current = unsafe_total  # 읽고
        unsafe_total = current + 1  # 쓴다


def safe_add() -> None:
    global safe_total
    for _ in range(100_000):
        with safe_lock:
            safe_total += 1


def step5_race() -> None:
    global unsafe_total, safe_total
    header("[5] 스레드 경합 - GIL이 있어도 안전하지 않다")

    unsafe_total = 0
    threads = [threading.Thread(target=unsafe_add) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    safe_total = 0
    threads = [threading.Thread(target=safe_add) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = 4 * 100_000
    print(f"   기대값        : {expected:>8,}")
    print(f"   락 없이       : {unsafe_total:>8,}   (차이 {expected - unsafe_total:,})")
    print(f"   락을 쓰면     : {safe_total:>8,}")
    print(
        """
 같은 문제가 DB에서는 lost update로 나타난다 (1주차 수요일)
   device.count = device.count + 1  ->  위험
   .update(count=F("count") + 1)    ->  안전
"""
    )


# ---------------------------------------------------------------


def main() -> None:
    print("=" * 62)
    print(" 1주차 금요일 통합 실험")
    print(f" 코어 수: {os.cpu_count()}   메인 PID: {os.getpid()}")
    print("=" * 62)

    step1_identity()
    step2_global_state()
    step3_shared_store()
    step4_gil()
    step5_race()


if __name__ == "__main__":
    main()


# ===============================================================
# 관찰 기록지
# ===============================================================
#
# 돌려보고 직접 채울 것. 예상과 다르게 나온 칸이 있으면 표시해 둔다.
#
# [1] 실행 주체
#     스레드 4개의 서로 다른 PID 개수 : ____
#     스레드 4개의 서로 다른 TID 개수 : ____
#     프로세스 4개의 서로 다른 PID 개수 : ____
#     -> TID가 예상만큼 안 나왔다면 왜인가?
#
# [2] 전역 변수
#     스레드 실행 시 최종값들 : ____
#     프로세스 실행 시 최종값들 : ____
#     -> 프로세스 쪽 값이 1부터 시작하지 않는다면 왜인가?
#        (힌트: 3주차 월요일 Copy-on-Write)
#
# [3] 공용 저장소
#     최종값들 : ____
#     PID 개수 : ____
#
# [4] GIL
#     IO + 스레드    워커 8일 때 배속 : ____
#     CPU + 스레드   워커 8일 때 배속 : ____
#     CPU + 프로세스 워커 8일 때 배속 : ____
#     이 기계의 코어 수 : ____
#     -> 세 번째 표의 배속이 안 올랐다면 왜인가?
#
# [5] 경합
#     락 없이 실행한 결과 : ____
#     -> 기대값과 정확히 같게 나왔는가?
#        같게 나왔다면, 코드에 버그가 없다는 뜻인가?
#        여러 번 돌려보면 어떻게 되는가?
#        (경합 버그가 위험한 이유가 여기에 있다)
#
# 정리 질문
#   1. 워커를 늘리면 전역 변수가 왜 어긋나는가
#   2. 그래서 상태를 어디에 두어야 하는가
#   3. IO 작업은 스레드로 되는데 CPU 작업은 왜 안 되는가
#   4. GIL이 있는데도 락이 왜 필요한가
#   5. 내 서비스의 worker 수는 무엇을 기준으로 정해야 하는가
