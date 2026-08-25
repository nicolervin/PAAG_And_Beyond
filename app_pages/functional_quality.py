from utils.functional_review_ui import render_functional_review_shell


render_functional_review_shell(
    title="Quality",
    description=(
        "Prepare quality observations and the future requirements review. "
        "This clean shell intentionally does not reuse the former Requirements page implementation."
    ),
    key_prefix="quality",
)
