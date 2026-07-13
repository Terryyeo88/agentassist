# STUB reasoning slice — TEST-ONLY, NOT a tax rule

> ⚠️ This file is a **test fixture** used only by
> `tests/test_reasoning_shell_generalize.py` to prove that the reasoning shell
> (`reasoning/reasoning_pass.py`) is skill-parameterized. It deliberately lives
> under `tests/fixtures/`, **NOT** under `knowledge-base/slices/`, so it can
> never be mistaken for a real Group-A skill. It encodes **no** Singapore GST
> semantics and authors **no** compliance rule.

The "stubskill" pass exists purely to exercise the generic seam:

- lines are filtered by a made-up `vat_group` marker,
- the model is asked to surface *candidates for human review only*,
- every candidate's `phrasing` must begin with "Consider reviewing whether".

Nothing here should be read as guidance about any real transaction.
