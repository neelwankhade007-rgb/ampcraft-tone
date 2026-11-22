import json
import os
from typing import List
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()


class AmpSettings(BaseModel):
    gain: float = Field(description="Numeric 0-10 value, or -1 if unknown")
    bass: float = Field(description="Numeric 0-10 value, or -1 if unknown")
    mids: float = Field(description="Numeric 0-10 value, or -1 if unknown")
    treble: float = Field(description="Numeric 0-10 value, or -1 if unknown")
    presence: float = Field(description="Numeric 0-10 value, or -1 if unknown")


class ExtractedSongRig(BaseModel):
    song: str
    artist: str
    tuning: str = Field(description="e.g., Drop C# (C# G# C# F# A# D#), E Standard, or Unknown")
    guitar_and_pickups: str = Field(description="Actual artist guitar & pickup position used on recording")
    primary_amp: str = Field(description="Actual studio primary amplifier (ignore 'budget alternative' suggestions)")
    secondary_or_blended_amp: str = Field(default="None", description="Secondary blended amp or 'None'")
    cabinet_and_speakers: str
    pedals_and_boosts: List[str]
    reported_amp_settings: AmpSettings
    source_urls: List[str] = Field(default_factory=list)
    confidence_score: int = Field(description="0-100 based on cross-source agreement on primary amp")
    verification_notes: str = Field(description="1-2 concise sentences summarizing source consensus")


def build_strict_schema(model_cls: type[BaseModel]) -> dict:
    """Enforces additionalProperties: false and full required arrays for Groq strict mode."""
    schema = model_cls.model_json_schema()

    def enforce_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for val in node.values():
                enforce_strict(val)
        elif isinstance(node, list):
            for item in node:
                enforce_strict(item)

    enforce_strict(schema)
    return schema


def get_llm_client() -> tuple[OpenAI, str]:
    """Uses Groq if GROQ_API_KEY is available in .env, otherwise falls back to local Ollama."""
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        return (
            OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key),
            "openai/gpt-oss-120b",
        )
    return (
        OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
        "qwen2.5:3b",
    )


def format_extracted_data(raw_json_path: str = "raw_extraction.json") -> ExtractedSongRig:
    with open(raw_json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    client, model_name = get_llm_client()
    print(f"Using model: {model_name}")

    context_blocks = []
    verified_urls = []

    for src in raw_data["sources"]:
        verified_urls.append(src["url"])
        best_chunks = "\n".join(c["text"] for c in src["chunks"][:2])
        context_blocks.append(f"--- SOURCE: {src['title']} ({src['url']}) ---\n{best_chunks}")

    compiled_context = "\n\n".join(context_blocks[:4])

    prompt = f"""
    Reconcile the ORIGINAL STUDIO RECORDING rig for "{raw_data['song']}" by {raw_data['artist']} from the sources below.

    CRITICAL EXTRACTION RULES:
    1. MAJORITY CONSENSUS WINS: If 2+ sources state the artist used a specific amp (e.g., Mesa/Boogie Dual Rectifier), that is the primary_amp. Ignore affiliate articles suggesting "affordable/close alternatives" (e.g., Peavey 5150 or PRS SE).
    2. NUMBERS ONLY FOR KNOBS: Output a single float (0.0 to 10.0) for gain, bass, mids, treble, and presence. Use -1 if unknown.
    3. PEDALS: Only list pedals actually used on the studio track, not optional cover recommendations.
    4. TUNING: Normalize Drop Db and Drop C# into clear notation if mentioned.

    SCRAPED SOURCES:
    {compiled_context}
    """

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "You are a precise audio forensics extractor. Reconcile multiple sources by majority consensus and output valid JSON matching the schema.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "extracted_song_rig",
                "strict": True,
                "schema": build_strict_schema(ExtractedSongRig),
            },
        },
        temperature=0.0,
    )

    raw_json_str = response.choices[0].message.content
    if not raw_json_str:
        raise ValueError("Model returned an empty response.")

    rig = ExtractedSongRig.model_validate_json(raw_json_str)
    rig.source_urls = verified_urls
    return rig


if __name__ == "__main__":
    formatted = format_extracted_data("raw_extraction.json")
    with open("verified_rig.json", "w", encoding="utf-8") as f:
        f.write(formatted.model_dump_json(indent=2))
    print(formatted.model_dump_json(indent=2))