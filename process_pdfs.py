import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import fitz  # PyMuPDF

class PDFOutlineExtractor:
    def __init__(self):
        # Font size thresholds for heading detection
        self.title_min_size = 16.0
        self.h1_min_size = 14.0
        self.h2_min_size = 12.0
        self.h3_min_size = 11.0
        self.body_text_size = 10.0
        
        # Heading patterns for text-based detection
        self.heading_patterns = [
            # Numbered patterns
            r'^(\d+\.?\s+[A-Z][^.!?]*?)$',  # "1. Introduction"
            r'^(\d+\.\d+\.?\s+[A-Z][^.!?]*?)$',  # "1.1 Background"
            r'^(\d+\.\d+\.\d+\.?\s+[A-Z][^.!?]*?)$',  # "1.1.1 Details"
            
            # Roman numerals
            r'^([IVX]+\.?\s+[A-Z][^.!?]*?)$',  # "I. Introduction"
            
            # Letter patterns
            r'^([A-Z]\.?\s+[A-Z][^.!?]*?)$',  # "A. Section"
            
            # Chapter/Section patterns
            r'^(Chapter\s+\d+[:\s]+[A-Z][^.!?]*?)$',
            r'^(Section\s+\d+[:\s]+[A-Z][^.!?]*?)$',
            
            # All caps headings (but not too long)
            r'^([A-Z\s]{3,30})$',
            
            # Title case without ending punctuation
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+[a-z]+)*)$'
        ]
        
    def extract_text_with_fonts(self, doc) -> List[Dict]:
        """Extract text with font information from PDF"""
        text_data = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if text and len(text) > 1:
                                text_data.append({
                                    "text": text,
                                    "size": span["size"],
                                    "flags": span["flags"],
                                    "font": span["font"],
                                    "page": page_num + 1,
                                    "bbox": span["bbox"]
                                })
        
        return text_data
    
    def is_bold(self, flags: int) -> bool:
        """Check if text is bold based on flags"""
        return bool(flags & 2**4)  # Bold flag
    
    def is_likely_heading(self, text: str, size: float, flags: int, avg_size: float) -> bool:
        """Determine if text is likely a heading based on multiple criteria"""
        text = text.strip()
        
        # Skip very short or very long text
        if len(text) < 3 or len(text) > 200:
            return False
            
        # Skip text that ends with common sentence endings
        if text.endswith(('.', '!', '?', ',', ';', ':')):
            # Allow if it matches specific patterns like "1.1 Introduction"
            if not any(re.match(pattern, text, re.IGNORECASE) for pattern in self.heading_patterns[:6]):
                return False
        
        # Font size criteria
        size_based = size > avg_size * 1.1
        
        # Bold text
        bold_text = self.is_bold(flags)
        
        # Pattern matching
        pattern_match = any(re.match(pattern, text, re.IGNORECASE) for pattern in self.heading_patterns)
        
        # Position-based (first significant text on page often headings)
        # This would need bbox analysis which we'll skip for simplicity
        
        # Combine criteria
        return (size_based and bold_text) or pattern_match or (size > avg_size * 1.3)
    
    def classify_heading_level(self, text: str, size: float, all_sizes: List[float]) -> Optional[str]:
        """Classify heading level based on size and content"""
        text = text.strip()
        
        # Sort unique sizes in descending order
        unique_sizes = sorted(set(all_sizes), reverse=True)
        
        # If we have clear size hierarchy
        if len(unique_sizes) >= 3:
            # Title: largest size
            if size >= unique_sizes[0] and size >= self.title_min_size:
                # Check if it looks like a title
                if (len(text.split()) <= 10 and 
                    not text.startswith(('1.', '2.', '3.', 'Chapter', 'Section')) and
                    not re.match(r'^\d+\.\d+', text)):
                    return "TITLE"
            
            # H1: Second largest or large size
            if size >= unique_sizes[1] or size >= self.h1_min_size:
                if self._looks_like_h1(text):
                    return "H1"
            
            # H2: Third largest or medium size
            if len(unique_sizes) > 2 and (size >= unique_sizes[2] or size >= self.h2_min_size):
                if self._looks_like_h2(text):
                    return "H2"
            
            # H3: Smaller but still above body text
            if size >= self.h3_min_size:
                if self._looks_like_h3(text):
                    return "H3"
        else:
            # Fallback to absolute size thresholds
            if size >= self.title_min_size and self._looks_like_title(text):
                return "TITLE"
            elif size >= self.h1_min_size and self._looks_like_h1(text):
                return "H1"
            elif size >= self.h2_min_size and self._looks_like_h2(text):
                return "H2"
            elif size >= self.h3_min_size and self._looks_like_h3(text):
                return "H3"
        
        return None
    
    def _looks_like_title(self, text: str) -> bool:
        """Check if text looks like a document title"""
        # Titles are usually short, don't start with numbers, and are descriptive
        return (len(text.split()) <= 10 and 
                not re.match(r'^\d+\.', text) and
                not text.startswith(('Chapter', 'Section', 'Part')))
    
    def _looks_like_h1(self, text: str) -> bool:
        """Check if text looks like H1 heading"""
        patterns = [
            r'^\d+\.?\s+',  # "1. " or "1 "
            r'^[IVX]+\.?\s+',  # Roman numerals
            r'^Chapter\s+\d+',
            r'^Part\s+[A-Z]',
            r'^[A-Z\s]{5,}$'  # All caps
        ]
        return any(re.match(pattern, text, re.IGNORECASE) for pattern in patterns)
    
    def _looks_like_h2(self, text: str) -> bool:
        """Check if text looks like H2 heading"""
        patterns = [
            r'^\d+\.\d+\.?\s+',  # "1.1 "
            r'^[A-Z]\.?\s+',     # "A. "
        ]
        return any(re.match(pattern, text, re.IGNORECASE) for pattern in patterns)
    
    def _looks_like_h3(self, text: str) -> bool:
        """Check if text looks like H3 heading"""
        patterns = [
            r'^\d+\.\d+\.\d+\.?\s+',  # "1.1.1 "
            r'^\([a-z]\)\s+',         # "(a) "
            r'^\d+\)\s+',             # "1) "
        ]
        return any(re.match(pattern, text, re.IGNORECASE) for pattern in patterns)
    
    def extract_outline(self, pdf_path: str) -> Dict:
        """Extract outline from PDF file"""
        try:
            doc = fitz.open(pdf_path)
            
            # First, try to get outline from PDF metadata
            toc = doc.get_toc()
            if toc:
                return self._process_toc(toc, doc)
            
            # Fallback to text analysis
            text_data = self.extract_text_with_fonts(doc)
            
            if not text_data:
                return {"title": Path(pdf_path).stem, "outline": []}
            
            # Calculate average font size
            sizes = [item["size"] for item in text_data]
            avg_size = sum(sizes) / len(sizes) if sizes else 12.0
            
            # Find potential headings
            headings = []
            title = None
            
            for item in text_data:
                if self.is_likely_heading(item["text"], item["size"], item["flags"], avg_size):
                    level = self.classify_heading_level(item["text"], item["size"], sizes)
                    if level:
                        if level == "TITLE" and not title:
                            title = item["text"]
                        elif level in ["H1", "H2", "H3"]:
                            headings.append({
                                "level": level,
                                "text": item["text"],
                                "page": item["page"]
                            })
            
            # If no title found, use first H1 or filename
            if not title:
                h1_headings = [h for h in headings if h["level"] == "H1"]
                if h1_headings:
                    title = h1_headings[0]["text"]
                    # Remove this H1 from headings to avoid duplication
                    headings = [h for h in headings if not (h["level"] == "H1" and h["text"] == title)]
                else:
                    title = Path(pdf_path).stem
            
            # Sort headings by page number
            headings.sort(key=lambda x: x["page"])
            
            doc.close()
            
            return {
                "title": title,
                "outline": headings
            }
            
        except Exception as e:
            print(f"Error processing {pdf_path}: {str(e)}")
            return {
                "title": Path(pdf_path).stem,
                "outline": []
            }
    
    def _process_toc(self, toc: List, doc) -> Dict:
        """Process table of contents from PDF metadata"""
        outline = []
        title = None
        
        for item in toc:
            level, text, page = item
            
            # Convert level to heading format
            if level == 1:
                heading_level = "H1"
            elif level == 2:
                heading_level = "H2"
            elif level == 3:
                heading_level = "H3"
            else:
                continue  # Skip deeper levels
            
            # Clean up text
            text = text.strip()
            if text:
                if not title and level == 1:
                    title = text
                else:
                    outline.append({
                        "level": heading_level,
                        "text": text,
                        "page": page
                    })
        
        if not title:
            title = doc.metadata.get("title", "Document")
            if not title or title == "Document":
                # Try to get title from first heading
                if outline and outline[0]["level"] == "H1":
                    title = outline[0]["text"]
                    outline = outline[1:]  # Remove first item
        
        return {
            "title": title or "Document",
            "outline": outline
        }


def process_pdfs():
    """Main processing function"""
    # Get input and output directories
    input_dir = Path("/app/input")
    output_dir = Path("/app/output")
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    extractor = PDFOutlineExtractor()
    
    # Get all PDF files
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        print("No PDF files found in input directory")
        return
    
    for pdf_file in pdf_files:
        try:
            # Extract outline (actual processing instead of dummy data)
            result = extractor.extract_outline(str(pdf_file))
            
            # Create output JSON file
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w", encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            print(f"Processed {pdf_file.name} -> {output_file.name}")
            
        except Exception as e:
            print(f"Error processing {pdf_file.name}: {str(e)}")
            # Create fallback output for failed files
            output_file = output_dir / f"{pdf_file.stem}.json"
            with open(output_file, "w") as f:
                json.dump({
                    "title": pdf_file.stem,
                    "outline": []
                }, f, indent=2)
            print(f"Processed {pdf_file.name} -> {output_file.name} (with errors)")


if __name__ == "__main__":
    print("Starting processing pdfs")
    process_pdfs()
    print("completed processing pdfs")