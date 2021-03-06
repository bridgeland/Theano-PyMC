import itertools

import pytest

import numpy as np
import numpy.linalg

import theano

from theano import tensor, function, grad, config
from theano.tensor.slinalg import (
    Cholesky,
    cholesky,
    CholeskyGrad,
    Solve,
    solve,
    eigvalsh,
    expm,
    kron,
)

from tests import unittest_tools as utt


def check_lower_triangular(pd, ch_f):
    ch = ch_f(pd)
    assert ch[0, pd.shape[1] - 1] == 0
    assert ch[pd.shape[0] - 1, 0] != 0
    assert np.allclose(np.dot(ch, ch.T), pd)
    assert not np.allclose(np.dot(ch.T, ch), pd)


def check_upper_triangular(pd, ch_f):
    ch = ch_f(pd)
    assert ch[4, 0] == 0
    assert ch[0, 4] != 0
    assert np.allclose(np.dot(ch.T, ch), pd)
    assert not np.allclose(np.dot(ch, ch.T), pd)


def test_cholesky():
    pytest.importorskip("scipy")
    rng = np.random.RandomState(utt.fetch_seed())
    r = rng.randn(5, 5).astype(config.floatX)
    pd = np.dot(r, r.T)
    x = tensor.matrix()
    chol = cholesky(x)
    # Check the default.
    ch_f = function([x], chol)
    check_lower_triangular(pd, ch_f)
    # Explicit lower-triangular.
    chol = Cholesky(lower=True)(x)
    ch_f = function([x], chol)
    check_lower_triangular(pd, ch_f)
    # Explicit upper-triangular.
    chol = Cholesky(lower=False)(x)
    ch_f = function([x], chol)
    check_upper_triangular(pd, ch_f)
    chol = Cholesky(lower=False, on_error="nan")(x)
    ch_f = function([x], chol)
    check_upper_triangular(pd, ch_f)


def test_cholesky_indef():
    scipy = pytest.importorskip("scipy")
    x = tensor.matrix()
    matrix = np.array([[1, 0.2], [0.2, -2]]).astype(config.floatX)
    cholesky = Cholesky(lower=True, on_error="raise")
    chol_f = function([x], cholesky(x))
    with pytest.raises(scipy.linalg.LinAlgError):
        chol_f(matrix)
    cholesky = Cholesky(lower=True, on_error="nan")
    chol_f = function([x], cholesky(x))
    assert np.all(np.isnan(chol_f(matrix)))


def test_cholesky_grad():
    pytest.importorskip("scipy")

    rng = np.random.RandomState(utt.fetch_seed())
    r = rng.randn(5, 5).astype(config.floatX)

    # The dots are inside the graph since Cholesky needs separable matrices

    # Check the default.
    utt.verify_grad(lambda r: cholesky(r.dot(r.T)), [r], 3, rng)
    # Explicit lower-triangular.
    utt.verify_grad(lambda r: Cholesky(lower=True)(r.dot(r.T)), [r], 3, rng)

    # Explicit upper-triangular.
    utt.verify_grad(lambda r: Cholesky(lower=False)(r.dot(r.T)), [r], 3, rng)


def test_cholesky_grad_indef():
    scipy = pytest.importorskip("scipy")
    x = tensor.matrix()
    matrix = np.array([[1, 0.2], [0.2, -2]]).astype(config.floatX)
    cholesky = Cholesky(lower=True, on_error="raise")
    chol_f = function([x], grad(cholesky(x).sum(), [x]))
    with pytest.raises(scipy.linalg.LinAlgError):
        chol_f(matrix)
    cholesky = Cholesky(lower=True, on_error="nan")
    chol_f = function([x], grad(cholesky(x).sum(), [x]))
    assert np.all(np.isnan(chol_f(matrix)))


@pytest.mark.slow
def test_cholesky_and_cholesky_grad_shape():
    pytest.importorskip("scipy")

    rng = np.random.RandomState(utt.fetch_seed())
    x = tensor.matrix()
    for l in (cholesky(x), Cholesky(lower=True)(x), Cholesky(lower=False)(x)):
        f_chol = theano.function([x], l.shape)
        g = tensor.grad(l.sum(), x)
        f_cholgrad = theano.function([x], g.shape)
        topo_chol = f_chol.maker.fgraph.toposort()
        topo_cholgrad = f_cholgrad.maker.fgraph.toposort()
        if config.mode != "FAST_COMPILE":
            assert sum([node.op.__class__ == Cholesky for node in topo_chol]) == 0
            assert (
                sum([node.op.__class__ == CholeskyGrad for node in topo_cholgrad]) == 0
            )
        for shp in [2, 3, 5]:
            m = np.cov(rng.randn(shp, shp + 10)).astype(config.floatX)
            np.testing.assert_equal(f_chol(m), (shp, shp))
            np.testing.assert_equal(f_cholgrad(m), (shp, shp))


def test_eigvalsh():
    scipy = pytest.importorskip("scipy")

    A = theano.tensor.dmatrix("a")
    B = theano.tensor.dmatrix("b")
    f = function([A, B], eigvalsh(A, B))

    rng = np.random.RandomState(utt.fetch_seed())
    a = rng.randn(5, 5)
    a = a + a.T
    for b in [10 * np.eye(5, 5) + rng.randn(5, 5)]:
        w = f(a, b)
        refw = scipy.linalg.eigvalsh(a, b)
        np.testing.assert_array_almost_equal(w, refw)

    # We need to test None separatly, as otherwise DebugMode will
    # complain, as this isn't a valid ndarray.
    b = None
    B = theano.tensor.NoneConst
    f = function([A], eigvalsh(A, B))
    w = f(a)
    refw = scipy.linalg.eigvalsh(a, b)
    np.testing.assert_array_almost_equal(w, refw)


def test_eigvalsh_grad():
    pytest.importorskip("scipy")

    rng = np.random.RandomState(utt.fetch_seed())
    a = rng.randn(5, 5)
    a = a + a.T
    b = 10 * np.eye(5, 5) + rng.randn(5, 5)
    tensor.verify_grad(
        lambda a, b: eigvalsh(a, b).dot([1, 2, 3, 4, 5]), [a, b], rng=np.random
    )


class TestSolve(utt.InferShapeTester):
    def setup_method(self):
        self.op_class = Solve
        self.op = Solve()
        super().setup_method()

    def test_infer_shape(self):
        pytest.importorskip("scipy")
        rng = np.random.RandomState(utt.fetch_seed())
        A = theano.tensor.matrix()
        b = theano.tensor.matrix()
        self._compile_and_check(
            [A, b],  # theano.function inputs
            [self.op(A, b)],  # theano.function outputs
            # A must be square
            [
                np.asarray(rng.rand(5, 5), dtype=config.floatX),
                np.asarray(rng.rand(5, 1), dtype=config.floatX),
            ],
            self.op_class,
            warn=False,
        )
        rng = np.random.RandomState(utt.fetch_seed())
        A = theano.tensor.matrix()
        b = theano.tensor.vector()
        self._compile_and_check(
            [A, b],  # theano.function inputs
            [self.op(A, b)],  # theano.function outputs
            # A must be square
            [
                np.asarray(rng.rand(5, 5), dtype=config.floatX),
                np.asarray(rng.rand(5), dtype=config.floatX),
            ],
            self.op_class,
            warn=False,
        )

    def test_solve_correctness(self):
        scipy = pytest.importorskip("scipy")
        rng = np.random.RandomState(utt.fetch_seed())
        A = theano.tensor.matrix()
        b = theano.tensor.matrix()
        y = self.op(A, b)
        gen_solve_func = theano.function([A, b], y)

        cholesky_lower = Cholesky(lower=True)
        L = cholesky_lower(A)
        y_lower = self.op(L, b)
        lower_solve_func = theano.function([L, b], y_lower)

        cholesky_upper = Cholesky(lower=False)
        U = cholesky_upper(A)
        y_upper = self.op(U, b)
        upper_solve_func = theano.function([U, b], y_upper)

        b_val = np.asarray(rng.rand(5, 1), dtype=config.floatX)

        # 1-test general case
        A_val = np.asarray(rng.rand(5, 5), dtype=config.floatX)
        # positive definite matrix:
        A_val = np.dot(A_val.transpose(), A_val)
        assert np.allclose(
            scipy.linalg.solve(A_val, b_val), gen_solve_func(A_val, b_val)
        )

        # 2-test lower traingular case
        L_val = scipy.linalg.cholesky(A_val, lower=True)
        assert np.allclose(
            scipy.linalg.solve_triangular(L_val, b_val, lower=True),
            lower_solve_func(L_val, b_val),
        )

        # 3-test upper traingular case
        U_val = scipy.linalg.cholesky(A_val, lower=False)
        assert np.allclose(
            scipy.linalg.solve_triangular(U_val, b_val, lower=False),
            upper_solve_func(U_val, b_val),
        )

    def test_solve_dtype(self):
        pytest.importorskip("scipy")

        dtypes = [
            "uint8",
            "uint16",
            "uint32",
            "uint64",
            "int8",
            "int16",
            "int32",
            "int64",
            "float16",
            "float32",
            "float64",
        ]

        A_val = np.eye(2)
        b_val = np.ones((2, 1))

        # try all dtype combinations
        for A_dtype, b_dtype in itertools.product(dtypes, dtypes):
            A = tensor.matrix(dtype=A_dtype)
            b = tensor.matrix(dtype=b_dtype)
            x = solve(A, b)
            fn = function([A, b], x)
            x_result = fn(A_val.astype(A_dtype), b_val.astype(b_dtype))

            assert x.dtype == x_result.dtype

    def verify_solve_grad(self, m, n, A_structure, lower, rng):
        # ensure diagonal elements of A relatively large to avoid numerical
        # precision issues
        A_val = (rng.normal(size=(m, m)) * 0.5 + np.eye(m)).astype(config.floatX)
        if A_structure == "lower_triangular":
            A_val = np.tril(A_val)
        elif A_structure == "upper_triangular":
            A_val = np.triu(A_val)
        if n is None:
            b_val = rng.normal(size=m).astype(config.floatX)
        else:
            b_val = rng.normal(size=(m, n)).astype(config.floatX)
        eps = None
        if config.floatX == "float64":
            eps = 2e-8
        solve_op = Solve(A_structure=A_structure, lower=lower)
        utt.verify_grad(solve_op, [A_val, b_val], 3, rng, eps=eps)

    def test_solve_grad(self):
        pytest.importorskip("scipy")
        rng = np.random.RandomState(utt.fetch_seed())
        structures = ["general", "lower_triangular", "upper_triangular"]
        for A_structure in structures:
            lower = A_structure == "lower_triangular"
            self.verify_solve_grad(5, None, A_structure, lower, rng)
            self.verify_solve_grad(6, 1, A_structure, lower, rng)
            self.verify_solve_grad(4, 3, A_structure, lower, rng)
        # lower should have no effect for A_structure == 'general' so also
        # check lower=True case
        self.verify_solve_grad(4, 3, "general", lower=True, rng=rng)


def test_expm():
    scipy = pytest.importorskip("scipy")
    rng = np.random.RandomState(utt.fetch_seed())
    A = rng.randn(5, 5).astype(config.floatX)

    ref = scipy.linalg.expm(A)

    x = tensor.matrix()
    m = expm(x)
    expm_f = function([x], m)

    val = expm_f(A)
    np.testing.assert_array_almost_equal(val, ref)


def test_expm_grad_1():
    # with symmetric matrix (real eigenvectors)
    pytest.importorskip("scipy")
    rng = np.random.RandomState(utt.fetch_seed())
    # Always test in float64 for better numerical stability.
    A = rng.randn(5, 5)
    A = A + A.T

    tensor.verify_grad(expm, [A], rng=rng)


def test_expm_grad_2():
    # with non-symmetric matrix with real eigenspecta
    pytest.importorskip("scipy")
    rng = np.random.RandomState(utt.fetch_seed())
    # Always test in float64 for better numerical stability.
    A = rng.randn(5, 5)
    w = rng.randn(5) ** 2
    A = (np.diag(w ** 0.5)).dot(A + A.T).dot(np.diag(w ** (-0.5)))
    assert not np.allclose(A, A.T)

    tensor.verify_grad(expm, [A], rng=rng)


def test_expm_grad_3():
    # with non-symmetric matrix (complex eigenvectors)
    pytest.importorskip("scipy")
    rng = np.random.RandomState(utt.fetch_seed())
    # Always test in float64 for better numerical stability.
    A = rng.randn(5, 5)

    tensor.verify_grad(expm, [A], rng=rng)


class TestKron(utt.InferShapeTester):

    rng = np.random.RandomState(43)

    def setup_method(self):
        self.op = kron
        super().setup_method()

    def test_perform(self):
        scipy = pytest.importorskip("scipy")

        for shp0 in [(2,), (2, 3), (2, 3, 4), (2, 3, 4, 5)]:
            x = tensor.tensor(dtype="floatX", broadcastable=(False,) * len(shp0))
            a = np.asarray(self.rng.rand(*shp0)).astype(config.floatX)
            for shp1 in [(6,), (6, 7), (6, 7, 8), (6, 7, 8, 9)]:
                if len(shp0) + len(shp1) == 2:
                    continue
                y = tensor.tensor(dtype="floatX", broadcastable=(False,) * len(shp1))
                f = function([x, y], kron(x, y))
                b = self.rng.rand(*shp1).astype(config.floatX)
                out = f(a, b)
                # Newer versions of scipy want 4 dimensions at least,
                # so we have to add a dimension to a and flatten the result.
                if len(shp0) + len(shp1) == 3:
                    scipy_val = scipy.linalg.kron(a[np.newaxis, :], b).flatten()
                else:
                    scipy_val = scipy.linalg.kron(a, b)
                utt.assert_allclose(out, scipy_val)

    def test_numpy_2d(self):
        for shp0 in [(2, 3)]:
            x = tensor.tensor(dtype="floatX", broadcastable=(False,) * len(shp0))
            a = np.asarray(self.rng.rand(*shp0)).astype(config.floatX)
            for shp1 in [(6, 7)]:
                if len(shp0) + len(shp1) == 2:
                    continue
                y = tensor.tensor(dtype="floatX", broadcastable=(False,) * len(shp1))
                f = function([x, y], kron(x, y))
                b = self.rng.rand(*shp1).astype(config.floatX)
                out = f(a, b)
                assert np.allclose(out, np.kron(a, b))
