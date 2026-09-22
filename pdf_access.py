"""Read original PDFs, recovering unreadable page trees in memory only."""
import io
from contextlib import contextmanager
import pdfplumber
from pypdf import PdfReader, PdfWriter


@contextmanager
def open_pdf(data):
    document = None
    try:
        try:
            document = pdfplumber.open(io.BytesIO(data))
            if not document.pages:
                raise ValueError('Primary reader returned zero pages')
        except Exception:
            if document is not None:
                document.close()
                document = None
            reader = PdfReader(io.BytesIO(data))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            if not writer.pages:
                raise ValueError('No readable PDF pages')
            if reader.metadata:
                writer.add_metadata({str(k):str(v) for k,v in reader.metadata.items() if v is not None})
            recovered = io.BytesIO()
            writer.write(recovered)
            recovered.seek(0)
            document = pdfplumber.open(recovered)
            document.reader_recovery = 'pypdf in-memory page-tree rebuild; original file unchanged'
        yield document
    finally:
        if document is not None:
            document.close()
