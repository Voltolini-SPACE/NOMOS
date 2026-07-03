"""Benchmark real dos KDFs do cofre (evidência do ciclo C2)."""
import time

from nomos.kernel import vault as v


def bench(label, fn, n=3):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    print(f"{label}: min={min(times):.0f}ms median={sorted(times)[n//2]:.0f}ms n={n}")


if __name__ == "__main__":
    salt = b"0123456789abcdef"
    bench(f"PBKDF2-SHA256 iter={v.KDF_ITERATIONS}", lambda: v._derive_pbkdf2("passphrase-de-teste", salt))
    if v.argon2_available():
        bench(
            f"Argon2id t={v.ARGON2_TIME_COST} m={v.ARGON2_MEMORY_KIB}KiB p={v.ARGON2_PARALLELISM}",
            lambda: v._derive_argon2id("passphrase-de-teste", salt),
        )
    else:
        print("Argon2id: lib ausente neste host")
