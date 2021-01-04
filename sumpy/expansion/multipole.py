__copyright__ = "Copyright (C) 2012 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import sumpy.symbolic as sym  # noqa

from sumpy.symbolic import vector_xreplace
from sumpy.expansion import (
    ExpansionBase, VolumeTaylorExpansion, LaplaceConformingVolumeTaylorExpansion,
    HelmholtzConformingVolumeTaylorExpansion,
    BiharmonicConformingVolumeTaylorExpansion)
from pytools import factorial

import logging
logger = logging.getLogger(__name__)


__doc__ = """

.. autoclass:: VolumeTaylorMultipoleExpansion
.. autoclass:: H2DMultipoleExpansion
.. autoclass:: Y2DMultipoleExpansion

"""


class MultipoleExpansionBase(ExpansionBase):
    pass


# {{{ volume taylor

class VolumeTaylorMultipoleExpansionBase(MultipoleExpansionBase):
    """
    Coefficients represent the terms in front of the kernel derivatives.
    """

    def coefficients_from_source(self, kernel, avec, bvec, rscale, sac=None):
        from sumpy.kernel import KernelWrapper
        if kernel is None:
            kernel = self.kernel

        from sumpy.tools import mi_power, mi_factorial

        if not self.use_rscale:
            rscale = 1

        if isinstance(kernel, KernelWrapper):
            result = [
                    kernel.postprocess_at_source(mi_power(avec, mi), avec)
                    / mi_factorial(mi) / rscale ** sum(mi)
                    for mi in self.get_full_coefficient_identifiers()]
        else:
            avec = [sym.UnevaluatedExpr(a * rscale**-1) for a in avec]

            result = [
                    mi_power(avec, mi) / mi_factorial(mi)
                    for mi in self.get_full_coefficient_identifiers()]
        return (
            self.expansion_terms_wrangler.get_stored_mpole_coefficients_from_full(
                result, rscale, sac=sac))

    def evaluate(self, kernel, coeffs, bvec, rscale, sac=None):
        from sumpy.tools import MiDerivativeTakerWrapper
        from pytools import single_valued
        if not self.use_rscale:
            rscale = 1

        taker = self.get_kernel_derivative_taker(bvec, rscale, sac)
        expr_dict = {(0,)*self.dim: 1}
        expr_dict = kernel.get_derivative_transformation_at_target(expr_dict)
        pp_nderivatives = single_valued(sum(mi) for mi in expr_dict.keys())

        result = []
        for coeff, mi in zip(coeffs, self.get_coefficient_identifiers()):
            wrapper = MiDerivativeTakerWrapper(taker, mi)
            mi_expr = kernel.postprocess_at_target(wrapper, bvec)
            # For details about this correction, see the explanation at
            # VolumeTaylorLocalExpansionBase.coefficients_from_source
            expr = coeff * mi_expr / rscale**pp_nderivatives
            result.append(expr)

        result = sym.Add(*tuple(result))
        return result

    def translate_from(self, src_expansion, src_coeff_exprs, src_rscale,
            dvec, tgt_rscale, sac=None):
        if not isinstance(src_expansion, type(self)):
            raise RuntimeError("do not know how to translate %s to "
                    "Taylor multipole expansion"
                               % type(src_expansion).__name__)

        if not self.use_rscale:
            src_rscale = 1
            tgt_rscale = 1

        logger.info("building translation operator: %s(%d) -> %s(%d): start"
                % (type(src_expansion).__name__,
                    src_expansion.order,
                    type(self).__name__,
                    self.order))

        from sumpy.tools import mi_factorial

        src_mi_to_index = {mi: i for i, mi in enumerate(
            src_expansion.get_coefficient_identifiers())}

        tgt_mi_to_index = {mi: i for i, mi in enumerate(
            self.get_full_coefficient_identifiers())}

        # This algorithm uses the observation that M2M coefficients
        # have the following form in 2D
        #
        # $T_{m, n} = \sum_{i\le m, j\le n} C_{i, j}
        #             d_x^i d_y^j \binom{m}{i} \binom{n}{j}$
        # and can be rewritten as follows.
        #
        # Let $Y_{m, n} = \sum_{i\le m} C_{i, n} d_x^i \binom{m}{i}$.
        #
        # Then, $T_{m, n} = \sum_{j\le n} Y_{m, j} d_y^j \binom{n}{j}$.
        #
        # $Y_{m, n}$ are $p^2$ temporary variables that are
        # reused for different M2M coefficients and costs $p$ per variable.
        # Total cost for calculating $Y_{m, n}$ is $p^3$ and similar
        # for $T_{m, n}$.

        # In other words, we're better off computing the translation
        # one dimension at a time. If the coefficient-identifying multi-indices
        # in the source expansion have the form (0, m) and (n, 0), where m>=0, n>=1,
        # then we calculate the output from (0, m) with the second
        # dimension as the fastest varying dimension and then calculate
        # the output from (n, 0) with the first dimension as the fastest
        # varying dimension.

        tgt_split = \
            self.expansion_terms_wrangler._get_coeff_identifier_split()
        result = [0] * len(self.get_full_coefficient_identifiers())

        for axis in range(self.dim):
            # In M2M, target order is the same or higher as source order.
            # First, let's write source coefficients in target coefficient
            # indices and then adjust rscale. Here C is referred by the same
            # name used in the formulae above.
            cur_dim_input_coeffs = \
                [0] * len(self.get_full_coefficient_identifiers())
            for d, mis in tgt_split:
                if d != axis:
                    continue
                for mi in mis:
                    if mi not in src_mi_to_index:
                        continue
                    src_idx = src_mi_to_index[mi]
                    tgt_idx = tgt_mi_to_index[mi]
                    cur_dim_input_coeffs[tgt_idx] = src_coeff_exprs[src_idx] * \
                            sym.UnevaluatedExpr(src_rscale/tgt_rscale)**sum(mi)

            if all(coeff == 0 for coeff in cur_dim_input_coeffs):
                continue

            # Use the axis as the last dimension to vary
            dims = list(range(axis)) + \
                   list(range(axis+1, self.dim)) + [axis]
            for d in dims:
                # We build the full target multipole and then compress it, below.
                cur_dim_output_coeffs = \
                    [0] * len(self.get_full_coefficient_identifiers())
                for i, tgt_mi in enumerate(
                        self.get_full_coefficient_identifiers()):

                    # Calling this input_mis instead of src_mis because we
                    # converted the source coefficients to target coefficient
                    # indices beforehand.
                    for mi_i in range(tgt_mi[d]+1):
                        input_mi = list(tgt_mi)
                        input_mi[d] = mi_i
                        input_mi = tuple(input_mi)
                        contrib = cur_dim_input_coeffs[tgt_mi_to_index[input_mi]]
                        for idim in range(self.dim):
                            n = tgt_mi[idim]
                            k = input_mi[idim]
                            assert n >= k
                            contrib /= factorial(n-k)
                            contrib *= \
                                sym.UnevaluatedExpr(dvec[idim]/tgt_rscale)**(n-k)

                        cur_dim_output_coeffs[i] += contrib
                # cur_dim_output_coeffs is the input in the next iteration
                cur_dim_input_coeffs = cur_dim_output_coeffs

            for i in range(len(cur_dim_output_coeffs)):
                result[i] += cur_dim_output_coeffs[i]

        # {{{ simpler, functionally equivalent code
        if 0:
            src_mi_to_index = dict((mi, i) for i, mi in enumerate(
                src_expansion.get_coefficient_identifiers()))
            result = [0] * len(self.get_full_coefficient_identifiers())

            for i, mi in enumerate(src_expansion.get_coefficient_identifiers()):
                src_coeff_exprs[i] *= mi_factorial(mi)

            from pytools import generate_nonnegative_integer_tuples_below as gnitb

            for i, tgt_mi in enumerate(
                    self.get_full_coefficient_identifiers()):

                tgt_mi_plus_one = tuple(mi_i + 1 for mi_i in tgt_mi)

                for src_mi in gnitb(tgt_mi_plus_one):
                    try:
                        src_index = src_mi_to_index[src_mi]
                    except KeyError:
                        # Omitted coefficients: not life-threatening
                        continue

                    contrib = src_coeff_exprs[src_index]

                    for idim in range(self.dim):
                        n = tgt_mi[idim]
                        k = src_mi[idim]
                        assert n >= k
                        from sympy import binomial
                        contrib *= (binomial(n, k)
                                * sym.UnevaluatedExpr(dvec[idim]/tgt_rscale)**(n-k))

                    result[i] += (contrib
                        * sym.UnevaluatedExpr(src_rscale/tgt_rscale)**sum(src_mi))

                result[i] /= mi_factorial(tgt_mi)
        # }}}

        logger.info("building translation operator: done")
        return (
            self.expansion_terms_wrangler.get_stored_mpole_coefficients_from_full(
                result, tgt_rscale, sac=sac))


class VolumeTaylorMultipoleExpansion(
        VolumeTaylorExpansion,
        VolumeTaylorMultipoleExpansionBase):

    def __init__(self, kernel, order, use_rscale=None):
        VolumeTaylorMultipoleExpansionBase.__init__(self, kernel, order, use_rscale)
        VolumeTaylorExpansion.__init__(self, kernel, order, use_rscale)


class LaplaceConformingVolumeTaylorMultipoleExpansion(
        LaplaceConformingVolumeTaylorExpansion,
        VolumeTaylorMultipoleExpansionBase):

    def __init__(self, kernel, order, use_rscale=None):
        VolumeTaylorMultipoleExpansionBase.__init__(self, kernel, order, use_rscale)
        LaplaceConformingVolumeTaylorExpansion.__init__(
                self, kernel, order, use_rscale)


class HelmholtzConformingVolumeTaylorMultipoleExpansion(
        HelmholtzConformingVolumeTaylorExpansion,
        VolumeTaylorMultipoleExpansionBase):

    def __init__(self, kernel, order, use_rscale=None):
        VolumeTaylorMultipoleExpansionBase.__init__(self, kernel, order, use_rscale)
        HelmholtzConformingVolumeTaylorExpansion.__init__(
                self, kernel, order, use_rscale)


class BiharmonicConformingVolumeTaylorMultipoleExpansion(
        BiharmonicConformingVolumeTaylorExpansion,
        VolumeTaylorMultipoleExpansionBase):

    def __init__(self, kernel, order, use_rscale=None):
        VolumeTaylorMultipoleExpansionBase.__init__(self, kernel, order, use_rscale)
        BiharmonicConformingVolumeTaylorExpansion.__init__(
                self, kernel, order, use_rscale)

# }}}


# {{{ 2D Hankel-based expansions

class _HankelBased2DMultipoleExpansion(MultipoleExpansionBase):
    def get_storage_index(self, k):
        return self.order+k

    def get_coefficient_identifiers(self):
        return list(range(-self.order, self.order+1))

    def coefficients_from_source(self, kernel, avec, bvec, rscale, sac=None):
        if not self.use_rscale:
            rscale = 1

        if kernel is None:
            kernel = self.kernel

        from sumpy.symbolic import sym_real_norm_2
        bessel_j = sym.Function("bessel_j")
        avec_len = sym_real_norm_2(avec)

        arg_scale = self.get_bessel_arg_scaling()

        # The coordinates are negated since avec points from source to center.
        source_angle_rel_center = sym.atan2(-avec[1], -avec[0])
        return [
                kernel.postprocess_at_source(
                    bessel_j(c, arg_scale * avec_len)
                    / rscale ** abs(c)
                    * sym.exp(sym.I * c * -source_angle_rel_center),
                    avec)
                for c in self.get_coefficient_identifiers()]

    def evaluate(self, kernel, coeffs, bvec, rscale, sac=None):
        if not self.use_rscale:
            rscale = 1

        from sumpy.symbolic import sym_real_norm_2
        hankel_1 = sym.Function("hankel_1")
        bvec_len = sym_real_norm_2(bvec)
        target_angle_rel_center = sym.atan2(bvec[1], bvec[0])

        arg_scale = self.get_bessel_arg_scaling()

        return sum(coeffs[self.get_storage_index(c)]
                   * kernel.postprocess_at_target(
                       hankel_1(c, arg_scale * bvec_len)
                       * rscale ** abs(c)
                       * sym.exp(sym.I * c * target_angle_rel_center), bvec)
                for c in self.get_coefficient_identifiers())

    def translate_from(self, src_expansion, src_coeff_exprs, src_rscale,
            dvec, tgt_rscale, sac=None):
        if not isinstance(src_expansion, type(self)):
            raise RuntimeError("do not know how to translate %s to %s"
                               % (type(src_expansion).__name__,
                                   type(self).__name__))

        if not self.use_rscale:
            src_rscale = 1
            tgt_rscale = 1

        from sumpy.symbolic import sym_real_norm_2
        dvec_len = sym_real_norm_2(dvec)
        bessel_j = sym.Function("bessel_j")
        new_center_angle_rel_old_center = sym.atan2(dvec[1], dvec[0])

        arg_scale = self.get_bessel_arg_scaling()

        translated_coeffs = []
        for j in self.get_coefficient_identifiers():
            translated_coeffs.append(
                sum(src_coeff_exprs[src_expansion.get_storage_index(m)]
                    * bessel_j(m - j, arg_scale * dvec_len)
                    * src_rscale ** abs(m)
                    / tgt_rscale ** abs(j)
                    * sym.exp(sym.I * (m - j) * new_center_angle_rel_old_center)
                for m in src_expansion.get_coefficient_identifiers()))
        return translated_coeffs


class H2DMultipoleExpansion(_HankelBased2DMultipoleExpansion):
    def __init__(self, kernel, order, use_rscale=None):
        from sumpy.kernel import HelmholtzKernel
        assert (isinstance(kernel.get_base_kernel(), HelmholtzKernel)
                and kernel.dim == 2)

        super().__init__(
                kernel, order, use_rscale=use_rscale)

    def get_bessel_arg_scaling(self):
        return sym.Symbol(self.kernel.get_base_kernel().helmholtz_k_name)


class Y2DMultipoleExpansion(_HankelBased2DMultipoleExpansion):
    def __init__(self, kernel, order, use_rscale=None):
        from sumpy.kernel import YukawaKernel
        assert (isinstance(kernel.get_base_kernel(), YukawaKernel)
                and kernel.dim == 2)

        super().__init__(
                kernel, order, use_rscale=use_rscale)

    def get_bessel_arg_scaling(self):
        return sym.I * sym.Symbol(self.kernel.get_base_kernel().yukawa_lambda_name)

# }}}

# vim: fdm=marker
