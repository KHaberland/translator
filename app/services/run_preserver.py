from docx.text.paragraph import Paragraph


XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def replace_paragraph_text_preserving_runs(
    paragraph: Paragraph,
    translated_text: str,
) -> None:
    run_elements = _text_run_elements(paragraph)
    if not run_elements:
        paragraph.add_run(translated_text)
        return

    chunks = _split_text_by_original_runs(
        translated_text,
        [_run_text(run_element) for run_element in run_elements],
    )

    for run_element, chunk in zip(run_elements, chunks, strict=True):
        _replace_run_text(run_element, chunk)


def _text_run_elements(paragraph: Paragraph) -> list[object]:
    return [
        run_element
        for run_element in paragraph._p.xpath(".//w:r")
        if run_element.xpath(".//w:t")
    ]


def _run_text(run_element: object) -> str:
    return "".join(text_element.text or "" for text_element in run_element.xpath(".//w:t"))


def _split_text_by_original_runs(
    translated_text: str,
    original_run_texts: list[str],
) -> list[str]:
    if len(original_run_texts) == 1:
        return [translated_text]

    total_original_length = sum(len(text) for text in original_run_texts)
    if total_original_length <= 0:
        return [translated_text] + [""] * (len(original_run_texts) - 1)

    chunks: list[str] = []
    previous_boundary = 0
    cumulative_original_length = 0

    for original_text in original_run_texts[:-1]:
        cumulative_original_length += len(original_text)
        boundary = round(
            len(translated_text) * cumulative_original_length / total_original_length
        )
        chunks.append(translated_text[previous_boundary:boundary])
        previous_boundary = boundary

    chunks.append(translated_text[previous_boundary:])
    return chunks


def _replace_run_text(run_element: object, text: str) -> None:
    text_elements = run_element.xpath(".//w:t")
    if not text_elements:
        return

    text_elements[0].text = text
    _set_space_preserve(text_elements[0], text)

    for text_element in text_elements[1:]:
        text_element.text = ""
        _set_space_preserve(text_element, "")


def _set_space_preserve(text_element: object, text: str) -> None:
    if text.startswith(" ") or text.endswith(" "):
        text_element.set(XML_SPACE, "preserve")
    elif text_element.get(XML_SPACE) == "preserve":
        text_element.attrib.pop(XML_SPACE, None)
