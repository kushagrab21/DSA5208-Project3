// Loop pragmas for the three builds of the same kernels.
//
//   CPU build (default):   OpenMP threads inside each MPI rank ("parallel for" over the outer loops, "simd" inside).
//   Offload build:         -DP3_OFFLOAD (CMake option P3_OFFLOAD=ON): the same loops become OpenMP "target" regions
//                          for one GPU per rank (nvhpc -mp=gpu on Vanda). UNTESTED until it is run on Vanda.
//   No OpenMP:             the pragmas vanish and the loops run serially.
//
// Every kernel loop in this code base uses one of these macros, so the CPU and GPU builds run the same loop bodies.
#pragma once

#define P3_PRAGMA_(x) _Pragma(#x)
#define P3_PRAGMA(x) P3_PRAGMA_(x)

#if defined(P3_OFFLOAD)
// 1, 2 or 3 perfectly nested loops, all collapsed onto the device. P3_SIMD must expand to nothing here so that the
// loops stay perfectly nested.
#  define P3_FOR1(clauses) P3_PRAGMA(omp target teams distribute parallel for clauses)
#  define P3_FOR2(clauses) P3_PRAGMA(omp target teams distribute parallel for collapse(2) clauses)
#  define P3_FOR3(clauses) P3_PRAGMA(omp target teams distribute parallel for collapse(3) clauses)
#  define P3_SIMD(clauses)
#elif defined(_OPENMP)
// Threads share the outer loop(s); the innermost, contiguous loop is vectorised.
#  define P3_FOR1(clauses) P3_PRAGMA(omp parallel for simd schedule(static) clauses)
#  define P3_FOR2(clauses) P3_PRAGMA(omp parallel for schedule(static) clauses)
#  define P3_FOR3(clauses) P3_PRAGMA(omp parallel for collapse(2) schedule(static) clauses)
#  define P3_SIMD(clauses) P3_PRAGMA(omp simd clauses)
#else
#  define P3_FOR1(clauses)
#  define P3_FOR2(clauses)
#  define P3_FOR3(clauses)
#  define P3_SIMD(clauses)
#endif

#ifndef PLANT_HALO_BUG
#  define PLANT_HALO_BUG 0
#endif
