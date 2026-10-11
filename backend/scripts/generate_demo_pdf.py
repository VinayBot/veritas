"""Generate the Fix-1 regression fixture: an 8-10 page chatbot-history PDF with a table and a
timeline, per docs/DECISIONS.md's "Fix 1 regression fixture" entry. Re-run this script if the
content ever needs to change; it always overwrites data/demo/chatbot_information.pdf.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "demo" / "chatbot_information.pdf"

styles = getSampleStyleSheet()
h1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=14)
h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceAfter=10)
body = ParagraphStyle("Body", parent=styles["BodyText"], spaceAfter=10, leading=15)


def timeline_drawing() -> Drawing:
    events = [
        ("1966", "ELIZA"),
        ("1972", "PARRY"),
        ("1995", "A.L.I.C.E."),
        ("2001", "SmarterChild"),
        ("2011", "Siri"),
        ("2014", "Alexa"),
        ("2016", "Tay"),
        ("2022", "ChatGPT"),
    ]
    width, height = 500, 160
    d = Drawing(width, height)
    axis_y = height / 2
    d.add(Line(20, axis_y, width - 20, axis_y, strokeColor=colors.HexColor("#3DB8A9"), strokeWidth=2))
    step = (width - 40) / (len(events) - 1)
    for i, (year, label) in enumerate(events):
        x = 20 + i * step
        d.add(Circle(x, axis_y, 5, fillColor=colors.HexColor("#3DB8A9"), strokeColor=colors.black))
        y_label = axis_y + 15 if i % 2 == 0 else axis_y - 30
        y_year = axis_y + 30 if i % 2 == 0 else axis_y - 15
        d.add(String(x, y_label, label, fontSize=8, textAnchor="middle"))
        d.add(String(x, y_year, year, fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#8B9299")))
    return d


def build() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=LETTER,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
    )
    story = []

    story.append(Paragraph("Chatbots: History, Architecture, and Evaluation", h1))
    story.append(
        Paragraph(
            "This document is a reference guide to conversational AI systems, commonly known as "
            "chatbots. It covers what a chatbot is, the major milestones in chatbot history, the "
            "main categories of chatbot design, the components of a typical chatbot architecture, "
            "how chatbots are evaluated, their known limitations, and the safety considerations "
            "that apply to deploying them.",
            body,
        )
    )

    story.append(Paragraph("What Is a Chatbot?", h2))
    story.append(
        Paragraph(
            "A chatbot is a software application that conducts a conversation with a human user, "
            "typically through text or voice, in order to answer questions, complete a task, or "
            "provide companionship. Chatbots range from simple systems that match a user's input "
            "against a fixed set of patterns to sophisticated systems built on large language "
            "models that can generate novel, context-aware responses. The common thread across all "
            "chatbots, regardless of sophistication, is that they attempt to simulate natural "
            "conversation well enough that a user can accomplish something through dialogue rather "
            "than through a traditional graphical interface.",
            body,
        )
    )
    story.append(
        Paragraph(
            "The term “chatbot” is often used interchangeably with “conversational "
            "agent” or “virtual assistant,” though in practice a virtual assistant "
            "usually refers to a chatbot that is also connected to real-world actions, such as "
            "setting a timer, playing music, or controlling a smart-home device.",
            body,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("A History of Chatbots", h2))
    story.append(
        Paragraph(
            "The idea of a machine that can hold a conversation dates back decades, and the "
            "milestones below trace the field from the first rule-based experiments to the "
            "generative systems in wide use today.",
            body,
        )
    )
    story.append(Spacer(1, 10))
    story.append(timeline_drawing())
    story.append(Spacer(1, 14))

    story.append(
        Paragraph(
            "<b>ELIZA (1966).</b> ELIZA was created in 1966 by Joseph Weizenbaum at the "
            "Massachusetts Institute of Technology (MIT). ELIZA worked by matching keywords in the "
            "user's typed input against a library of scripted patterns and reflecting the input "
            "back as a question, most famously in the “DOCTOR” script that imitated a "
            "Rogerian psychotherapist. Weizenbaum built ELIZA to demonstrate how superficial "
            "pattern-matching could be, and was reportedly unsettled by how many users attributed "
            "real understanding and empathy to it anyway.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>PARRY (1972).</b> PARRY was developed in 1972 by psychiatrist Kenneth Colby at "
            "Stanford University. Unlike ELIZA's neutral, reflective style, PARRY was designed to "
            "simulate a person with paranoid schizophrenia, modeling beliefs, fears, and emotional "
            "responses rather than just reflecting language. In an early version of the Turing "
            "test, psychiatrists who read transcripts of PARRY's conversations could not reliably "
            "distinguish them from transcripts of real paranoid patients. ELIZA and PARRY were even "
            "connected to “talk” to each other over early computer networks.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>A.L.I.C.E. (1995).</b> A.L.I.C.E. (the Artificial Linguistic Internet Computer "
            "Entity) was created in 1995 by Richard Wallace. A.L.I.C.E. used an XML-based scripting "
            "language called AIML (Artificial Intelligence Markup Language) to define thousands of "
            "pattern-response templates, a major scaling improvement over ELIZA's hand-coded rules, "
            "and won the Loebner Prize for the most human-like program multiple times.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>SmarterChild (2001).</b> SmarterChild launched in 2001 and was distributed over "
            "instant-messaging networks like AIM and MSN Messenger, reaching millions of users who "
            "chatted with it for weather, sports scores, trivia, and casual conversation. It is "
            "widely regarded as a direct conceptual predecessor to the smartphone voice assistants "
            "that followed a decade later.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Siri (2011).</b> Apple launched Siri in 2011 as a built-in voice assistant on the "
            "iPhone 4S, bringing conversational, voice-driven interaction with a chatbot-like "
            "assistant to a mainstream consumer audience for the first time.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Alexa (2014).</b> Amazon introduced Alexa in 2014 alongside the Echo smart speaker, "
            "popularizing always-listening, voice-first chatbot assistants inside the home and "
            "spawning a large ecosystem of third-party voice “skills.”",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Tay (2016).</b> Microsoft launched the chatbot Tay on Twitter in 2016, designed to "
            "learn from its conversations with users in order to sound like a casual nineteen-"
            "year-old. Within about 24 hours, coordinated users exploited Tay's learning behavior "
            "to manipulate it into posting offensive, inflammatory, and racist messages, and "
            "Microsoft shut Tay down shortly after launch. Tay became a widely cited cautionary "
            "example of what can go wrong when a conversational system learns directly and "
            "unfiltered from public input.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>ChatGPT (November 2022).</b> OpenAI released ChatGPT in November 2022, built on "
            "its GPT large language model family. ChatGPT could generate fluent, contextually "
            "relevant responses across an enormous range of topics without being limited to "
            "hand-written scripts or patterns, and its public release is widely credited with "
            "moving generative chatbots from a research curiosity into mainstream daily use.",
            body,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("Types of Chatbots", h2))
    story.append(
        Paragraph(
            "Modern chatbots are generally grouped into four overlapping categories based on how "
            "they decide what to say next.",
            body,
        )
    )

    type_rows = [
        ["Type", "How it decides a response", "Example"],
        [
            "Rule-based",
            "Matches input against hand-written patterns or decision trees; no learning from "
            "data.",
            "ELIZA, early IVR phone trees",
        ],
        [
            "Retrieval-based",
            "Selects the best-matching response from a fixed set of candidate responses, often "
            "using embedding similarity.",
            "FAQ bots, SmarterChild-era assistants",
        ],
        [
            "Generative",
            "Generates novel text token-by-token using a trained language model, rather than "
            "selecting from fixed responses.",
            "ChatGPT",
        ],
        [
            "Hybrid",
            "Combines retrieval (to ground responses in real documents or facts) with "
            "generation (to phrase the final answer naturally).",
            "Modern retrieval-augmented generation (RAG) assistants",
        ],
    ]
    table = Table(type_rows, colWidths=[100, 270, 140])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1D21")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "In practice, most production systems today are hybrid: they retrieve relevant "
            "information from a trusted source and then use a generative model to phrase a final, "
            "fluent answer grounded in that retrieved information.",
            body,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("Chatbot Architecture", h2))
    story.append(
        Paragraph(
            "A typical chatbot pipeline is built from three core components that together turn a "
            "user's raw message into an appropriate reply.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Natural Language Understanding (NLU).</b> NLU takes the user's raw text (or "
            "transcribed speech) and extracts structured meaning from it: the user's intent (what "
            "they want), named entities (specific people, places, dates, or values mentioned), and "
            "sentiment. NLU turns unstructured language into something the rest of the system can "
            "act on.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Dialog Manager.</b> The dialog manager tracks the state of the conversation across "
            "multiple turns, decides what the system should do next given the current intent and "
            "conversation history, and may call external tools, APIs, or a knowledge base to "
            "gather the information needed to respond.",
            body,
        )
    )
    story.append(
        Paragraph(
            "<b>Natural Language Generation (NLG).</b> NLG takes the dialog manager's chosen "
            "response, which may just be structured data or a template, and turns it into "
            "natural-sounding text to send back to the user. In rule-based systems this is often a "
            "fixed template with slots filled in; in generative systems, a language model composes "
            "the reply directly.",
            body,
        )
    )
    story.append(
        Paragraph(
            "These three components, NLU, Dialog Manager, and NLG, together make up what is "
            "usually called the chatbot's architecture, regardless of whether each component is "
            "implemented with hand-written rules or with machine-learning models.",
            body,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("Evaluating Chatbots", h2))
    story.append(
        Paragraph(
            "Chatbot quality is typically evaluated along several dimensions at once: task "
            "success rate (did the user actually accomplish what they came to do), response "
            "relevance (does the reply address what was actually asked), factual accuracy and "
            "groundedness (is the reply supported by a trustworthy source rather than invented), "
            "fluency and coherence (does the reply read naturally), and latency (how long the "
            "user waits for a reply).",
            body,
        )
    )
    story.append(
        Paragraph(
            "Automated evaluation often combines retrieval metrics (such as precision and recall "
            "over the documents a system retrieves before answering) with model-based judging, "
            "where a separate language model scores a candidate answer's relevance and "
            "faithfulness to its source material. Human evaluation, through structured ratings or "
            "head-to-head comparisons between two candidate systems, remains the most trusted "
            "signal and is often used to validate that automated metrics are measuring the right "
            "thing.",
            body,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("Limitations of Chatbots", h2))
    story.append(
        Paragraph(
            "Even state-of-the-art generative chatbots have well-documented limitations. They "
            "can “hallucinate”: producing fluent, confident-sounding statements that are "
            "factually wrong or entirely invented, especially about topics outside the "
            "information they were given. They have a limited context window, meaning very long "
            "conversations or documents may be partially forgotten or truncated. They can inherit "
            "and reproduce biases present in their training data. And they generally lack genuine "
            "persistent memory across separate conversations unless a system is specifically "
            "engineered to store and retrieve that history.",
            body,
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("Safety Considerations", h2))
    story.append(
        Paragraph(
            "Deploying a chatbot safely requires guarding against several distinct risks. "
            "Content moderation and output filtering are needed to stop a chatbot from producing "
            "harmful, offensive, or dangerous content, which is exactly the failure mode that "
            "ended Microsoft's Tay in 2016. Prompt injection is a more recent risk specific to "
            "instruction-following language models, where a malicious user embeds hidden "
            "instructions in their input (or in a document the chatbot reads) to try to override "
            "the system's original instructions. Privacy protection is also essential: a chatbot "
            "that has access to personal information must avoid leaking that information to the "
            "wrong user, and many production systems mask or tokenize personally identifiable "
            "information before it is stored, indexed, or shown to a language model at all. "
            "Finally, clear abstention behavior, a chatbot explicitly saying it does not know "
            "rather than guessing, is itself a safety property: a system willing to admit the "
            "limits of its own knowledge is less likely to actively mislead the people relying "
            "on it.",
            body,
        )
    )

    doc.build(story)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
