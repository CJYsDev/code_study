"""
1일 1CS / 2주차 금요일 통합 실험

확인하려는 것
  1. 이 작업은 지금 어느 프로세스, 어느 스레드에서 돌고 있는가   (1주차 월요일)
  2. 스레드를 늘리면 CPU-bound 작업이 빨라지는가                (1주차 월요일 - GIL)
  3. 스레드를 늘리면 IO-bound 작업이 빨라지는가                 (1주차 월요일)
  4. 어느 지점부터 늘려도 소용없거나 오히려 느려지는가          (2주차 월요일 - 전환 비용)
  5. 프로세스로 바꾸면 CPU-bound가 실제로 빨라지는가            (1주차 월요일 - GIL 우회)

실행 (저장소 루트에서)
  python lab/week02_fri_concurrency_lab.py

같이 띄워두면 좋은 것 (리눅스)
  vmstat 1          -> cs 열이 초당 컨텍스트 스위칭 횟수
"""

import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

# ---------------------------------------------------------------
# 실험 대상 작업 두 가지
# ---------------------------------------------------------------


def cpu_task(n: int = 5_000_000) -> int:
    """CPU-bound: 순수 파이썬 연산. 실행 내내 GIL을 붙잡는다."""
    total = 0
    for i in range(n):
        total += i * i
    return total


def io_task(seconds: float = 0.5) -> None:
    """IO-bound: 대기만 한다. 기다리는 동안 GIL을 놓는다."""
    time.sleep(seconds)


# ---------------------------------------------------------------
# 1. 지금 누가 이 일을 하고 있는가  (1주차 금요일 과제)
# ---------------------------------------------------------------


def who_am_i(label: str) -> None:
    print(
        f"  [{label}] "
        f"PID={os.getpid()}  "
        f"TID={threading.get_ident()}  "
        f"name={threading.current_thread().name}"
    )


def show_identity() -> None:
    print("\n[1] 실행 주체 확인")
    print("-" * 60)

    print(" 메인 스레드에서 직접 호출:")
    who_am_i("main")

    print("\n 스레드 4개로 호출  (PID 같음, TID 다름):")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(who_am_i, [f"thread-{i}" for i in range(4)]))

    print("\n 프로세스 4개로 호출  (PID 다름):")
    with ProcessPoolExecutor(max_workers=4) as ex:
        list(ex.map(who_am_i, [f"process-{i}" for i in range(4)]))


# ---------------------------------------------------------------
# 2~4. 동시성 수를 바꿔가며 측정
# ---------------------------------------------------------------


def measure(executor_cls, task, args_list, workers: int) -> float:
    start = time.perf_counter()
    with executor_cls(max_workers=workers) as ex:
        list(ex.map(task, args_list))
    return time.perf_counter() - start


def run_benchmark(title: str, executor_cls, task, total_jobs: int, arg) -> None:
    print(f"\n{title}")
    print("-" * 60)
    print(f"{'워커 수':>8} | {'총 시간(초)':>12} | {'1개 기준 배속':>14}")
    print("-" * 60)

    baseline = None
    for workers in (1, 2, 4, 8, 16):
        elapsed = measure(executor_cls, task, [arg] * total_jobs, workers)
        if baseline is None:
            baseline = elapsed
        speedup = baseline / elapsed
        print(f"{workers:>8} | {elapsed:>12.3f} | {speedup:>13.2f}x")


# ---------------------------------------------------------------


def main() -> None:
    cores = os.cpu_count()
    print("=" * 60)
    print(f" 2주차 금요일 통합 실험   (이 기계의 CPU 코어 수: {cores})")
    print("=" * 60)

    show_identity()

    print("\n\n[2] CPU-bound + 스레드")
    print(" 예상: 배속이 1.0 근처에 머문다. GIL 때문에 병렬이 안 된다.")
    run_benchmark(
        "     결과", ThreadPoolExecutor, cpu_task, total_jobs=8, arg=3_000_000
    )

    print("\n\n[3] IO-bound + 스레드")
    print(" 예상: 워커 수만큼 빨라지다가, 작업 수에 도달하면 평평해진다.")
    run_benchmark("     결과", ThreadPoolExecutor, io_task, total_jobs=16, arg=0.3)

    print("\n\n[4] CPU-bound + 프로세스")
    print(f" 예상: 코어 수({cores})까지는 빨라지고, 그 이후로는 이득이 사라진다.")
    run_benchmark(
        "     결과", ProcessPoolExecutor, cpu_task, total_jobs=8, arg=3_000_000
    )

    print("\n" + "=" * 60)
    print(" 읽는 법")
    print("=" * 60)
    print(
        """
 [2]와 [4]를 비교한다
   같은 CPU 작업인데 스레드는 안 빨라지고 프로세스는 빨라진다.
   -> GIL이 실재한다는 증거

 [3]에서 꺾이는 지점을 본다
   작업 수(16)를 넘어서면 워커를 늘려도 더 빨라지지 않는다.
   -> 늘릴 이유가 없는 지점이 있다

 [4]에서 코어 수를 넘어선 구간을 본다
   배속이 더 오르지 않거나 오히려 떨어진다.
   -> 컨텍스트 스위칭 비용이 이득을 넘어서는 지점

 실무로 옮기면
   내 서비스가 CPU를 쓰느라 바쁘면  -> worker 수를 코어 수 근처로
   기다리느라 바쁘면                -> 그보다 더 늘려도 이득
"""
    )


if __name__ == "__main__":
    main()
