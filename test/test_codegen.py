from __future__ import division, absolute_import, print_function

__copyright__ = "Copyright (C) 2017 Matt Wala"

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


import sys

import logging
logger = logging.getLogger(__name__)


def test_kill_trivial_assignments():
    from pymbolic import var
    x, y, t0, t1, t2 = [var(s) for s in "x y t0 t1 t2".split()]

    assignments = (
        ("t0", 6),
        ("t1", -t0),
        ("t2", 6*x),
        ("nt", x**y),
        # users of trivial assignments
        ("u0", t0 + 1),
        ("u1", t1 + 1),
        ("u2", t2 + 1),
    )

    from sumpy.codegen import kill_trivial_assignments
    result = kill_trivial_assignments(
        assignments,
        retain_names=("u0", "u1", "u2"))

    from pymbolic.primitives import Sum

    def _s(*vals):
        return Sum(vals)

    assert result == [
        ('nt', x**y),
        ('u0', _s(6, 1)),
        ('u1', _s(-6, 1)),
        ('u2', _s(6*x, 1))]


def test_symbolic_assignment_name_uniqueness():
    # https://gitlab.tiker.net/inducer/sumpy/issues/13
    from sumpy.assignment_collection import SymbolicAssignmentCollection

    sac = SymbolicAssignmentCollection({"s_0": 1})
    sac.assign_unique("s_", 1)
    sac.assign_unique("s_", 1)
    assert len(sac.assignments) == 3

    sac = SymbolicAssignmentCollection()
    sac.assign_unique("s_0", 1)
    sac.assign_unique("s_", 1)
    sac.assign_unique("s_", 1)

    assert len(sac.assignments) == 3


# You can test individual routines by typing
# $ python test_fmm.py 'test_sumpy_fmm(cl.create_some_context)'

if __name__ == "__main__":
    if len(sys.argv) > 1:
        exec(sys.argv[1])
    else:
        from py.test.cmdline import main
        main([__file__])

# vim: fdm=marker
