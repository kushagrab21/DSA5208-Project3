#include "halo.hpp"

#include "par.hpp"

namespace {
// The two directions other than a, in increasing order.
void others(int a, int& b, int& c) {
    b = (a == 0) ? 1 : 0;
    c = (a == 2) ? 1 : 2;
}
int tag_up(int a) { return 10 + 2 * a; }  // message moving to the high neighbour
int tag_dn(int a) { return 11 + 2 * a; }  // message moving to the low neighbour
}  // namespace

Halo::Halo(const Grid& g) : G(g) {
    for (int a = 0; a < G.dim; ++a) {
        int b, c;
        others(a, b, c);
        for (int side = 0; side < 2; ++side) {
            Face& f = face(a, side);
            f.a = a;
            f.side = side;
            f.nbr = G.nbr[a][side];
            f.cnt = G.nl[b] * G.nl[c];
            // Buffers exist for boundary faces too: MPI_Sendrecv with MPI_PROC_NULL still needs a valid pointer.
            f.send.alloc(size_t(f.cnt));
            f.recv.alloc(size_t(f.cnt));
        }
    }
    req.resize(12);
}

long Halo::messages_per_exchange() const {
    long m = 0;
    for (int i = 0; i < 2 * G.dim; ++i)
        if (faces[i].nbr != MPI_PROC_NULL) ++m;
    return m;
}

long Halo::doubles_per_exchange() const {
    long d = 0;
    for (int i = 0; i < 2 * G.dim; ++i)
        if (faces[i].nbr != MPI_PROC_NULL) d += faces[i].cnt;
    return d;
}

void Halo::pack(const double* x, Face& f) {
    const int a = f.a;
    int b, c;
    others(a, b, c);
    long plane = (f.side == 0) ? G.g[a] : G.g[a] + G.nl[a] - 1;  // first or last interior plane
#if PLANT_HALO_BUG == 2
    // PLANTED BUG (shift): send the ghost plane instead of the last interior plane.
    if (a == 0 && f.side == 1) plane = G.g[a] + G.nl[a];
#endif
    const long str[3] = {G.S0, G.S1, 1};
    const long base = plane * str[a] + G.g[b] * str[b] + G.g[c] * str[c];
    const long nb = G.nl[b], nc = G.nl[c], sb = str[b], sc = str[c];
    double* buf = f.send.p;
    P3_FOR2()
    for (long u = 0; u < nb; ++u)
        P3_SIMD()
        for (long v = 0; v < nc; ++v) buf[u * nc + v] = x[base + u * sb + v * sc];
    f.send.to_host();
}

void Halo::unpack(double* x, Face& f) {
    const int a = f.a;
#if PLANT_HALO_BUG == 1
    // PLANTED BUG (skip): the received high-side face in direction 0 is dropped; that ghost layer stays zero.
    if (a == 0 && f.side == 1) return;
#endif
    int b, c;
    others(a, b, c);
    const long plane = (f.side == 0) ? 0 : G.g[a] + G.nl[a];  // ghost plane
    const long str[3] = {G.S0, G.S1, 1};
    const long base = plane * str[a] + G.g[b] * str[b] + G.g[c] * str[c];
    const long nb = G.nl[b], nc = G.nl[c], sb = str[b], sc = str[c];
    f.recv.to_dev();
    const double* buf = f.recv.p;
    P3_FOR2()
    for (long u = 0; u < nb; ++u)
        P3_SIMD()
        for (long v = 0; v < nc; ++v) x[base + u * sb + v * sc] = buf[u * nc + v];
}

void Halo::exchange_blocking(double* x) {
    for (int a = 0; a < G.dim; ++a) {
        Face& lo = face(a, 0);
        Face& hi = face(a, 1);
        if (lo.nbr == MPI_PROC_NULL && hi.nbr == MPI_PROC_NULL) continue;
        if (hi.nbr != MPI_PROC_NULL) pack(x, hi);
        if (lo.nbr != MPI_PROC_NULL) pack(x, lo);
        // Up: my last plane to the high neighbour, the low neighbour's last plane into my low ghost.
        MPI_Sendrecv(hi.send.p, int(hi.cnt), MPI_DOUBLE, hi.nbr, tag_up(a), lo.recv.p, int(lo.cnt), MPI_DOUBLE,
                     lo.nbr, tag_up(a), G.cart, MPI_STATUS_IGNORE);
        // Down: my first plane to the low neighbour, the high neighbour's first plane into my high ghost.
        MPI_Sendrecv(lo.send.p, int(lo.cnt), MPI_DOUBLE, lo.nbr, tag_dn(a), hi.recv.p, int(hi.cnt), MPI_DOUBLE,
                     hi.nbr, tag_dn(a), G.cart, MPI_STATUS_IGNORE);
        if (lo.nbr != MPI_PROC_NULL) unpack(x, lo);
        if (hi.nbr != MPI_PROC_NULL) unpack(x, hi);
    }
}

void Halo::start(double* x) {
    int k = 0;
    for (int i = 0; i < 2 * G.dim; ++i) {
        Face& f = faces[i];
        if (f.nbr == MPI_PROC_NULL) continue;
        MPI_Irecv(f.recv.p, int(f.cnt), MPI_DOUBLE, f.nbr, f.side == 0 ? tag_up(f.a) : tag_dn(f.a), G.cart,
                  &req[k++]);
    }
    for (int i = 0; i < 2 * G.dim; ++i) {
        Face& f = faces[i];
        if (f.nbr == MPI_PROC_NULL) continue;
        pack(x, f);
        MPI_Isend(f.send.p, int(f.cnt), MPI_DOUBLE, f.nbr, f.side == 1 ? tag_up(f.a) : tag_dn(f.a), G.cart,
                  &req[k++]);
    }
    for (int i = k; i < 12; ++i) req[i] = MPI_REQUEST_NULL;
}

void Halo::finish(double* x) {
    MPI_Waitall(12, req.data(), MPI_STATUSES_IGNORE);
    for (int i = 0; i < 2 * G.dim; ++i) {
        Face& f = faces[i];
        if (f.nbr != MPI_PROC_NULL) unpack(x, f);
    }
}
