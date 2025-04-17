from datetime import timedelta
from celery import shared_task
from django.utils import timezone

from .utils import get_key_points
from .models import Room, Quiz, Summary
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import random
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

# Course-specific subtopics for distractors
COURSE_SUBTOPICS = {
    # Architecture
    "Architectural Design": ["Sustainable Design", "Interior Architecture", "Landscape Architecture"],
    "Building Construction": ["Construction Materials", "Structural Systems", "Construction Management"],
    "Urban Planning": ["City Planning", "Urban Design", "Transportation Planning"],

    # CEE
    "Structural Analysis": ["Finite Element Analysis", "Structural Dynamics", "Bridge Design"],
    "Environmental Engineering": ["Water Treatment", "Waste Management", "Air Quality Control"],
    "Transportation Engineering": ["Traffic Engineering", "Pavement Design", "Transport Modeling"],

    # CSE
    "Data Structures": ["Arrays and Linked Lists", "Trees and Graphs", "Hash Tables"],
    "Algorithms": [
        "Sorting Algorithms", "Graph Algorithms", "Dynamic Programming",
        # Adding more specific terms for sorting algorithms
        "Bubble Sort", "Selection Sort", "Insertion Sort", "Merge Sort", "Quick Sort",
        "Heap Sort", "Radix Sort", "Bucket Sort", "Counting Sort", "Shell Sort"
    ],
    "Database Systems": ["Database Management", "SQL Queries", "NoSQL Databases"],

    # EEE
    "Circuit Analysis": ["AC/DC Circuits", "Network Theorems", "Transient Analysis"],
    "Power Systems": ["Power Generation", "Transmission Lines", "Power Distribution"],
    "Microprocessors": ["Microprocessor Architecture", "Assembly Language", "Interfacing Techniques"],

    # ETE
    "Wireless Communication": ["Mobile Networks", "Wireless Protocols", "Antenna Design"],
    "Signal Processing": ["Digital Signal Processing", "Fourier Transforms", "Filter Design"],
    "Network Security": ["Cryptography", "Firewall Systems", "Ethical Hacking"],

    # Biochemistry
    "Genetic Engineering": ["Gene Cloning", "CRISPR Technology", "Recombinant DNA"],
    "Molecular Biology": ["DNA Replication", "Protein Synthesis", "Gene Expression"],
    "Enzymology": ["Enzyme Kinetics", "Enzyme Inhibition", "Cofactors and Coenzymes"],

    # ESM
    "Climate Change": ["Global Warming", "Carbon Footprint", "Climate Modeling"],
    "Sustainability Science": ["Renewable Energy", "Sustainable Development", "Circular Economy"],
    "Environmental Policy": ["Environmental Laws", "Policy Analysis", "International Agreements"],

    # Microbiology
    "Virology": ["Viral Replication", "Vaccine Development", "Antiviral Drugs"],
    "Immunology": ["Immune Response", "Antibodies", "Vaccines"],
    "Bacteriology": ["Bacterial Growth", "Antibiotics", "Pathogenic Bacteria"],

    # BPharm
    "Pharmaceutical Chemistry": ["Drug Synthesis", "Medicinal Chemistry", "Pharmacokinetics"],
    "Pharmacology": ["Drug Action", "Therapeutics", "Side Effects"],
    "Pharmaceutics": ["Drug Delivery Systems", "Formulation Development", "Biopharmaceutics"],

    # BBA
    "Marketing Management": ["Market Research", "Branding Strategies", "Digital Marketing"],
    "Financial Accounting": ["Balance Sheets", "Income Statements", "Cash Flow Analysis"],
    "Human Resource Management": ["Recruitment Strategies", "Employee Motivation", "Performance Appraisal"],

    # English
    "Literary Theory": ["Structuralism", "Postmodernism", "Feminist Criticism"],
    "Linguistics": ["Phonetics", "Syntax", "Semantics"],
    "Creative Writing": ["Fiction Writing", "Poetry", "Screenwriting"],

    # Law
    "Constitutional Law": ["Fundamental Rights", "Judicial Review", "Separation of Powers"],
    "Criminal Law": ["Criminal Procedure", "Evidence Law", "Penal Code"],
    "International Law": ["Treaty Law", "Human Rights Law", "Law of the Sea"],

    # MAJ
    "Media Ethics": ["Journalistic Integrity", "Media Bias", "Privacy Issues"],
    "Broadcast Journalism": ["News Production", "TV Reporting", "Radio Broadcasting"],
    "Advertising": ["Ad Campaigns", "Consumer Behavior", "Media Planning"]
}

# Define course-specific question templates
QUESTION_TEMPLATES = {
    "Architectural Design": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to achieve {key_point} in architecture?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a sustainable practice in architecture?", "correct_answer": lambda kp: "True" if "Sustainable" in kp else "False", "options": ["True", "False"]}
    ],
    "Building Construction": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is critical for {key_point} in construction?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a structural component in building construction?", "correct_answer": lambda kp: "True" if "Structural" in kp else "False", "options": ["True", "False"]}
    ],
    "Urban Planning": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to improve {key_point} in urban areas?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} focus on transportation in urban planning?", "correct_answer": lambda kp: "True" if "Transportation" in kp else "False", "options": ["True", "False"]}
    ],
    "Structural Analysis": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which method is used in {key_point} for structural analysis?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} used in bridge design?", "correct_answer": lambda kp: "True" if "Bridge" in kp else "False", "options": ["True", "False"]}
    ],
    "Environmental Engineering": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to address {key_point} in environmental engineering?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} focus on water quality?", "correct_answer": lambda kp: "True" if "Water" in kp else "False", "options": ["True", "False"]}
    ],
    "Transportation Engineering": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to improve {key_point} in transportation systems?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} related to traffic flow?", "correct_answer": lambda kp: "True" if "Traffic" in kp else "False", "options": ["True", "False"]}
    ],
    "Data Structures": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "example", "template": "Which of the following is an example of {key_point}?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a linear data structure?", "correct_answer": lambda kp: "True" if "Arrays" in kp or "Linked Lists" in kp else "False", "options": ["True", "False"]}
    ],
    "Algorithms": [
        {"type": "definition", "template": "Which sorting algorithm is represented by {key_point}?", "correct_answer": "{key_point}"},
        {"type": "time_complexity", "template": "What is the average time complexity of {key_point}?", "correct_answer": lambda kp: {
            "Bubble Sort": "O(n^2)", "Selection Sort": "O(n^2)", "Insertion Sort": "O(n^2)",
            "Merge Sort": "O(n log n)", "Quick Sort": "O(n log n)", "Heap Sort": "O(n log n)",
            "Radix Sort": "O(nk)", "Bucket Sort": "O(n + k)", "Counting Sort": "O(n + k)",
            "Shell Sort": "O(n^1.3)"
        }.get(kp, "O(n^2)")},
        {"type": "use_case", "template": "Which scenario is {key_point} best suited for?", "correct_answer": lambda kp: {
            "Bubble Sort": "Small datasets with few swaps", "Selection Sort": "Minimizing swaps",
            "Insertion Sort": "Nearly sorted data", "Merge Sort": "Large datasets with stable sorting",
            "Quick Sort": "General-purpose sorting", "Heap Sort": "Guaranteed O(n log n) with in-place sorting",
            "Radix Sort": "Integer sorting with fixed-length keys", "Bucket Sort": "Uniformly distributed data",
            "Counting Sort": "Small range of integers", "Shell Sort": "Medium-sized datasets"
        }.get(kp, "General-purpose sorting")},
        {"type": "true_false", "template": "Is {key_point} a stable sorting algorithm?", "correct_answer": lambda kp: "True" if kp in ["Merge Sort", "Insertion Sort", "Bubble Sort", "Radix Sort", "Counting Sort", "Bucket Sort"] else "False", "options": ["True", "False"]}
    ],
    "Database Systems": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "example", "template": "Which of the following is an example of {key_point}?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a relational database concept?", "correct_answer": lambda kp: "True" if "SQL" in kp else "False", "options": ["True", "False"]}
    ],
    "Circuit Analysis": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to analyze {key_point} in circuits?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} apply to AC circuits?", "correct_answer": lambda kp: "True" if "AC" in kp else "False", "options": ["True", "False"]}
    ],
    "Power Systems": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is critical for {key_point} in power systems?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} related to power generation?", "correct_answer": lambda kp: "True" if "Generation" in kp else "False", "options": ["True", "False"]}
    ],
    "Microprocessors": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for microprocessors?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve programming in assembly language?", "correct_answer": lambda kp: "True" if "Assembly" in kp else "False", "options": ["True", "False"]}
    ],
    "Wireless Communication": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to improve {key_point} in wireless systems?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} related to mobile networks?", "correct_answer": lambda kp: "True" if "Mobile" in kp else "False", "options": ["True", "False"]}
    ],
    "Signal Processing": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for signal processing?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve Fourier transforms?", "correct_answer": lambda kp: "True" if "Fourier" in kp else "False", "options": ["True", "False"]}
    ],
    "Network Security": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to ensure {key_point} in network security?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a method to prevent cyber attacks?", "correct_answer": lambda kp: "True" if "Firewall" in kp or "Cryptography" in kp else "False", "options": ["True", "False"]}
    ],
    "Genetic Engineering": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for genetic engineering?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve gene editing?", "correct_answer": lambda kp: "True" if "CRISPR" in kp else "False", "options": ["True", "False"]}
    ],
    "Molecular Biology": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is critical for {key_point} in molecular biology?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve DNA replication?", "correct_answer": lambda kp: "True" if "DNA" in kp else "False", "options": ["True", "False"]}
    ],
    "Enzymology": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to study {key_point} in enzymology?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve enzyme kinetics?", "correct_answer": lambda kp: "True" if "Kinetics" in kp else "False", "options": ["True", "False"]}
    ],
    "Climate Change": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to mitigate {key_point} in climate change?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} contribute to global warming?", "correct_answer": lambda kp: "True" if "Carbon" in kp else "False", "options": ["True", "False"]}
    ],
    "Sustainability Science": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept promotes {key_point} in sustainability?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} related to renewable energy?", "correct_answer": lambda kp: "True" if "Renewable" in kp else "False", "options": ["True", "False"]}
    ],
    "Environmental Policy": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to enforce {key_point} in environmental policy?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} an international agreement?", "correct_answer": lambda kp: "True" if "International" in kp else "False", "options": ["True", "False"]}
    ],
    "Virology": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to study {key_point} in virology?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve vaccine development?", "correct_answer": lambda kp: "True" if "Vaccine" in kp else "False", "options": ["True", "False"]}
    ],
    "Immunology": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is critical for {key_point} in immunology?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve the immune response?", "correct_answer": lambda kp: "True" if "Immune" in kp else "False", "options": ["True", "False"]}
    ],
    "Bacteriology": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to address {key_point} in bacteriology?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve antibiotics?", "correct_answer": lambda kp: "True" if "Antibiotics" in kp else "False", "options": ["True", "False"]}
    ],
    "Pharmaceutical Chemistry": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for pharmaceutical chemistry?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve drug synthesis?", "correct_answer": lambda kp: "True" if "Drug Synthesis" in kp else "False", "options": ["True", "False"]}
    ],
    "Pharmacology": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is critical for {key_point} in pharmacology?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} study drug action?", "correct_answer": lambda kp: "True" if "Drug Action" in kp else "False", "options": ["True", "False"]}
    ],
    "Pharmaceutics": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for pharmaceutics?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve drug delivery systems?", "correct_answer": lambda kp: "True" if "Drug Delivery" in kp else "False", "options": ["True", "False"]}
    ],
    "Marketing Management": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to improve {key_point} in marketing?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} related to digital marketing?", "correct_answer": lambda kp: "True" if "Digital" in kp else "False", "options": ["True", "False"]}
    ],
    "Financial Accounting": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to prepare {key_point} in financial accounting?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve balance sheets?", "correct_answer": lambda kp: "True" if "Balance" in kp else "False", "options": ["True", "False"]}
    ],
    "Human Resource Management": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to enhance {key_point} in HR?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve employee motivation?", "correct_answer": lambda kp: "True" if "Motivation" in kp else "False", "options": ["True", "False"]}
    ],
    "Literary Theory": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to analyze {key_point} in literary theory?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a feminist approach in literary theory?", "correct_answer": lambda kp: "True" if "Feminist" in kp else "False", "options": ["True", "False"]}
    ],
    "Linguistics": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to study {key_point} in linguistics?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve phonetics?", "correct_answer": lambda kp: "True" if "Phonetics" in kp else "False", "options": ["True", "False"]}
    ],
    "Creative Writing": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for creative writing?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve poetry writing?", "correct_answer": lambda kp: "True" if "Poetry" in kp else "False", "options": ["True", "False"]}
    ],
    "Constitutional Law": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is critical for {key_point} in constitutional law?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve judicial review?", "correct_answer": lambda kp: "True" if "Judicial" in kp else "False", "options": ["True", "False"]}
    ],
    "Criminal Law": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for criminal law?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve evidence law?", "correct_answer": lambda kp: "True" if "Evidence" in kp else "False", "options": ["True", "False"]}
    ],
    "International Law": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to enforce {key_point} in international law?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve human rights law?", "correct_answer": lambda kp: "True" if "Human Rights" in kp else "False", "options": ["True", "False"]}
    ],
    "Media Ethics": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to address {key_point} in media ethics?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve journalistic integrity?", "correct_answer": lambda kp: "True" if "Journalistic" in kp else "False", "options": ["True", "False"]}
    ],
    "Broadcast Journalism": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used in {key_point} for broadcast journalism?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve TV reporting?", "correct_answer": lambda kp: "True" if "TV" in kp else "False", "options": ["True", "False"]}
    ],
    "Advertising": [
        {"type": "definition", "template": "What is a key concept in {key_point}?", "correct_answer": "{key_point}"},
        {"type": "application", "template": "Which concept is used to improve {key_point} in advertising?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Does {key_point} involve consumer behavior?", "correct_answer": lambda kp: "True" if "Consumer" in kp else "False", "options": ["True", "False"]}
    ],
    "generic": [
        {"type": "definition", "template": "What is a key concept related to {key_point}?", "correct_answer": "{key_point}"},
        {"type": "example", "template": "Which of the following is an example of {key_point}?", "correct_answer": "{key_point}"},
        {"type": "true_false", "template": "Is {key_point} a fundamental concept?", "correct_answer": "True", "options": ["True", "False"]}
    ]
}

def generate_dynamic_distractors(summary_text, correct_answer, num_distractors=3):
    kw_model = KeyBERT(model=SentenceTransformer('all-MiniLM-L6-v2'))
    keywords = kw_model.extract_keywords(
        summary_text,
        keyphrase_ngram_range=(1, 2),
        stop_words='english',
        top_n=10,
        use_mmr=True,
        diversity=0.7
    )
    distractors = [keyword for keyword, score in keywords if keyword.lower() != correct_answer.lower()]
    if len(distractors) < num_distractors:
        logger.warning(f"Not enough dynamic distractors. Falling back to generic.")
        distractors.extend([f"Alternative Concept {i}" for i in range(1, 4) if f"Alternative Concept {i}" != correct_answer])
    return random.sample(distractors, min(num_distractors, len(distractors)))

def generate_quiz_questions(room, key_points=None):
    num_questions = 5

    if key_points is None:
        summaries = Summary.objects.filter(room=room).order_by('-uploaded_at')
        if not summaries.exists():
            logger.warning(f"No summaries found for room {room.id}. Cannot generate quiz questions.")
            return

        latest_summary = summaries.first()
        pdf_text = latest_summary.summary_text
        if not pdf_text:
            logger.warning(f"No summary text available for room {room.id}.")
            return

        key_points = get_key_points(pdf_text)
        if not key_points:
            logger.warning(f"No key points extracted for room {room.id}.")
            return

    # Filter out vague key points
    key_points = [kp for kp in key_points if len(kp.split()) <= 3 and kp.lower() not in ["example", "device", "stored"]]
    if not key_points:
        logger.warning(f"No valid key points after filtering for room {room.id}. Using fallback.")
        course = room.course.strip() if room.course else "generic"
        key_points = COURSE_SUBTOPICS.get(course, ["Concept A", "Concept B", "Concept C"])

    # Determine the course for distractors and question templates
    course = room.course.strip() if room.course else "generic"
    distractors = COURSE_SUBTOPICS.get(course, ["Concept A", "Concept B", "Concept C"])
    question_templates = QUESTION_TEMPLATES.get(course, QUESTION_TEMPLATES["generic"])
    logger.info(f"Selected course: {course}, Distractors: {distractors}, Question Templates: {[qt['type'] for qt in question_templates]}")

    logger.info(f"Generating quiz questions with key points: {key_points}")
    for i in range(min(num_questions, len(key_points))):
        key_point = key_points[i]

        # Randomly select a question template
        question_template = random.choice(question_templates)
        question_type = question_template["type"]
        question = question_template["template"].format(key_point=key_point)

        # Determine the correct answer
        if callable(question_template["correct_answer"]):
            correct_answer = question_template["correct_answer"](key_point)
        else:
            correct_answer = question_template["correct_answer"].format(key_point=key_point)

        # Handle True/False questions separately
        if question_type == "true_false":
            options = question_template["options"]
            all_options = options.copy()
            correct_answer_key = "A" if correct_answer == "True" else "B"
            options_dict = {
                'A': all_options[0],
                'B': all_options[1]
            }
        else:
            # Select incorrect options from the course-specific distractors
            available_distractors = [term for term in distractors if term.lower() != key_point.lower() and term.lower() != correct_answer.lower()]
            logger.info(f"Key point: {key_point}, Available distractors: {available_distractors}")

            # For specific question types like time_complexity or use_case in Algorithms
            if course == "Algorithms" and question_type == "time_complexity":
                available_distractors = ["O(n)", "O(n^2)", "O(n log n)", "O(nk)", "O(n + k)"]
                available_distractors = [d for d in available_distractors if d != correct_answer]
                incorrect_options = random.sample(available_distractors, min(3, len(available_distractors)))
            elif course == "Algorithms" and question_type == "use_case":
                available_distractors = [
                    "Small datasets with few swaps", "Minimizing swaps", "Nearly sorted data",
                    "Large datasets with stable sorting", "General-purpose sorting",
                    "Guaranteed O(n log n) with in-place sorting", "Integer sorting with fixed-length keys",
                    "Uniformly distributed data", "Small range of integers", "Medium-sized datasets"
                ]
                available_distractors = [d for d in available_distractors if d != correct_answer]
                incorrect_options = random.sample(available_distractors, min(3, len(available_distractors)))
            else:
                if len(available_distractors) < 3:
                    logger.warning(f"Not enough distractors available for key point {key_point} in course {course}. Generating dynamic distractors.")
                    available_distractors = generate_dynamic_distractors(latest_summary.summary_text, key_point, num_distractors=3)
                    if len(available_distractors) < 3:
                        logger.warning(f"Not enough dynamic distractors. Using placeholders.")
                        incorrect_options = [
                            f"Alternative Concept 1",
                            f"Alternative Concept 2",
                            f"Alternative Concept 3"
                        ]
                    else:
                        incorrect_options = available_distractors
                else:
                    incorrect_options = random.sample(available_distractors, min(3, len(available_distractors)))

            # Combine correct and incorrect options, shuffle them
            all_options = [correct_answer] + incorrect_options
            random.shuffle(all_options)

            # Assign options to A, B, C, D and determine the correct answer key
            options_dict = {
                'A': all_options[0],
                'B': all_options[1],
                'C': all_options[2],
                'D': all_options[3]
            }
            correct_answer_key = next(key for key, value in options_dict.items() if value == correct_answer)
            logger.info(f"Options for question {i+1}: {options_dict}, Correct answer: {correct_answer_key}")

        # Create Quiz object in the database
        try:
            Quiz.objects.create(
                room=room,
                question=question,
                options=json.dumps(options_dict),
                correct_answer=correct_answer_key
            )
            logger.info(f"Generated quiz question {i+1} for room {room.id}: {question}")
        except Exception as e:
            logger.error(f"Failed to create quiz question {i+1} for room {room.id}: {str(e)}")
            continue

@shared_task
def start_quiz_for_room(room_id):
    logger.info(f"Starting start_quiz_for_room for room {room_id}")
    try:
        room = Room.objects.get(id=room_id)
        # Clear existing quizzes to ensure fresh generation
        Quiz.objects.filter(room=room).delete()
        logger.info(f"Cleared existing quizzes for room {room_id}")

        summaries = room.summaries.all()
        if not summaries:
            logger.warning(f"No summaries available for room {room_id}")
            return
        
        combined_text = " ".join(summary.summary_text for summary in summaries)
        logger.info(f"Combined summary text length: {len(combined_text)} characters")
        
        try:
            kw_model = KeyBERT(model=SentenceTransformer('all-MiniLM-L6-v2'))
            key_points = kw_model.extract_keywords(
                combined_text,
                keyphrase_ngram_range=(1, 2),
                stop_words='english',
                top_n=10,
                use_mmr=True,
                diversity=0.7
            )
            key_points = [keyword for keyword, score in key_points]
            logger.info(f"Extracted key points: {key_points}")
        except Exception as e:
            logger.error(f"Error extracting key points: {str(e)}", exc_info=True)
            key_points = []
        
        if not key_points:
            latest_summary = summaries.first()
            if latest_summary and latest_summary.key_points:
                key_points = json.loads(latest_summary.key_points)
            else:
                key_points = [room.course]
            logger.info(f"Fallback key points: {key_points}")
        
        try:
            generate_quiz_questions(room, key_points)
            logger.info(f"Generated quiz questions for room {room_id}")
        except Exception as e:
            logger.error(f"Error generating quiz questions for room {room_id}: {str(e)}", exc_info=True)
            return

        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                logger.error("Channel layer is None. Cannot send quiz start notification.")
                return
            async_to_sync(channel_layer.group_send)(
                f'room_{room.id}',
                {
                    'type': 'quiz_start_notification',
                    'message': 'Quiz has been started!'
                }
            )
            logger.info(f"Quiz start notification sent for room {room_id}")
        except Exception as e:
            logger.error(f"Error sending quiz start notification for room {room_id}: {str(e)}", exc_info=True)
            return

        logger.info(f"Quiz started for room {room_id}")
    except Room.DoesNotExist:
        logger.error(f"Room {room_id} does not exist.")
    except Exception as e:
        logger.error(f"Error in start_quiz_for_room: {str(e)}", exc_info=True)
        raise

@shared_task
def check_and_start_quizzes():
    logger.info("Starting check_and_start_quizzes task")
    try:
        current_time = timezone.now()
        logger.info(f"Current time: {current_time}")
        
        rooms = Room.objects.all()
        logger.info(f"Found {rooms.count()} rooms")
        
        for room in rooms:
            logger.info(f"Checking room {room.id}: {room.title}")
            start_datetime = room.get_start_datetime()
            quiz_start_time = start_datetime + timedelta(minutes=20)
            logger.info(f"Room start: {start_datetime}, Quiz start: {quiz_start_time}")
            
            time_diff = (current_time - quiz_start_time).total_seconds()
            logger.info(f"Time difference: {time_diff} seconds")
            
            if time_diff >= 0:
                if not room.quizzes.exists():
                    logger.info(f"Triggering quiz start for room {room.id} at {current_time}")
                    start_quiz_for_room.delay(room.id)
                else:
                    logger.info(f"Quiz already exists for room {room.id}")
            else:
                logger.info(f"Room {room.id} not ready for quiz (time_diff: {time_diff})")
    except Exception as e:
        logger.error(f"Error in check_and_start_quizzes: {str(e)}", exc_info=True)
        raise