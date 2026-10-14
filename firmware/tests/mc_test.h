/* Minimal dependency-free test harness for host unit tests. */
#ifndef SEMMC_MC_TEST_H
#define SEMMC_MC_TEST_H

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int mc_test_failures = 0;
static int mc_test_checks = 0;

#define CHECK(cond)                                                                 \
    do {                                                                            \
        mc_test_checks++;                                                           \
        if (!(cond)) {                                                              \
            mc_test_failures++;                                                     \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                           \
    } while (0)

#define CHECK_NEAR(a, b, tol)                                                                    \
    do {                                                                                         \
        mc_test_checks++;                                                                        \
        const double _a = (double)(a), _b = (double)(b), _t = (double)(tol);                     \
        if (!(fabs(_a - _b) <= _t)) {                                                            \
            mc_test_failures++;                                                                  \
            fprintf(stderr, "%s:%d: CHECK_NEAR failed: %s=%.9g %s=%.9g tol=%.3g\n", __FILE__,   \
                    __LINE__, #a, _a, #b, _b, _t);                                               \
        }                                                                                        \
    } while (0)

#define CHECK_EQ_INT(a, b)                                                                        \
    do {                                                                                          \
        mc_test_checks++;                                                                         \
        const long _a = (long)(a), _b = (long)(b);                                                \
        if (_a != _b) {                                                                           \
            mc_test_failures++;                                                                   \
            fprintf(stderr, "%s:%d: CHECK_EQ failed: %s=%ld %s=%ld\n", __FILE__, __LINE__, #a, _a, \
                    #b, _b);                                                                      \
        }                                                                                         \
    } while (0)

#define RUN(fn)                                \
    do {                                       \
        const int _before = mc_test_failures;  \
        fn();                                  \
        printf("%-48s %s\n", #fn, mc_test_failures == _before ? "ok" : "FAIL"); \
    } while (0)

#define TEST_MAIN_END()                                                                 \
    do {                                                                                \
        printf("%d checks, %d failures\n", mc_test_checks, mc_test_failures);           \
        return mc_test_failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;                     \
    } while (0)

#endif
