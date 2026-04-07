"""
LinkedIn content generator -- creates copy-paste-ready content.

All output is TEXT only. No automated posting or messaging.
- Profile optimization suggestions
- LinkedIn post drafts
- Recruiter outreach messages
"""

from typing import Optional


def _get_client(profile: dict = None):
    """Get unified LLM client (Ollama local or OpenAI) from secrets."""
    from src.utils.llm_provider import create_llm_client, load_secrets

    client = create_llm_client(load_secrets())
    if not client:
        raise ValueError(
            "No LLM configured. Install Ollama from https://ollama.ai (run `ollama pull llama3.2`) "
            "or set openai_api_key in secrets.yaml — see secrets.template.yaml."
        )
    return client


def _profile_summary(profile: dict) -> str:
    """Build a text summary of the user's profile for LLM context."""
    personal = profile.get("personal", {})
    skills = profile.get("skills", {})
    edu = profile.get("education", [])

    lines = [
        f"Name: {personal.get('first_name', '')} {personal.get('last_name', '')}",
        f"Location: {personal.get('location', '')}",
        f"Experience: {profile.get('years_of_experience', 3)} years",
        f"Level: {profile.get('experience_level', 'mid')}",
        f"Target roles: {', '.join(profile.get('target_roles', []))}",
    ]
    for category, items in skills.items():
        if isinstance(items, list) and items:
            lines.append(f"{category}: {', '.join(items)}")
    for e in edu:
        lines.append(f"Education: {e.get('degree', '')} in {e.get('field', '')} from {e.get('university', '')}")

    return "\n".join(lines)


def generate_post(topic: str, profile: dict, tone: str = "professional") -> str:
    """Generate a LinkedIn post draft about a topic/project."""
    client = _get_client()
    summary = _profile_summary(profile)

    prompt = (
        f"Write a LinkedIn post for the following professional:\n{summary}\n\n"
        f"Topic: {topic}\n"
        f"Tone: {tone}\n\n"
        "The post should:\n"
        "- Start with a strong hook line that grabs attention\n"
        "- Tell a brief story or share an insight (3-5 short paragraphs)\n"
        "- End with a call to action or question for engagement\n"
        "- Include 3-5 relevant hashtags at the end\n"
        "- Be 150-250 words\n"
        "- Use line breaks between paragraphs for readability\n"
        "- Sound authentic, not AI-generated\n\n"
        "Return ONLY the post text, ready to copy-paste into LinkedIn."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write engaging LinkedIn posts. Return only the post content."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error generating post: {e}"


def generate_recruiter_message(
    company_or_role: str,
    profile: dict,
    message_type: str = "initial",
) -> str:
    """Generate a personalized recruiter outreach message."""
    client = _get_client()
    summary = _profile_summary(profile)

    type_instruction = {
        "initial": "Write an initial cold outreach message to a recruiter.",
        "follow_up": "Write a follow-up message after no response to an initial outreach.",
        "thank_you": "Write a thank-you message after an interview.",
    }.get(message_type, "Write an initial cold outreach message.")

    prompt = (
        f"Professional profile:\n{summary}\n\n"
        f"Target: {company_or_role}\n\n"
        f"{type_instruction}\n\n"
        "Requirements:\n"
        "- Keep it under 150 words\n"
        "- Reference the specific company/role\n"
        "- Mention 1-2 relevant skills or experiences\n"
        "- Be professional but warm, not robotic\n"
        "- Include a clear ask (conversation, call, etc.)\n"
        "- Don't be overly flattering or desperate\n\n"
        "Return ONLY the message text, ready to copy-paste."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write professional networking messages. Return only the message."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error generating message: {e}"


def optimize_profile(profile: dict) -> str:
    """Generate LinkedIn profile optimization suggestions."""
    client = _get_client()
    summary = _profile_summary(profile)

    prompt = (
        f"Review this professional's profile and provide LinkedIn optimization suggestions:\n\n"
        f"{summary}\n\n"
        "Provide specific, actionable suggestions for:\n"
        "1. **Headline** - Write 2-3 optimized headline options (keyword-rich for recruiter search)\n"
        "2. **About Section** - Write a compelling about section (200-300 words)\n"
        "3. **Skills to highlight** - Which skills to feature prominently\n"
        "4. **Keywords to add** - Industry keywords that recruiters search for\n"
        "5. **Quick wins** - 3-5 easy changes for immediate improvement\n\n"
        "Focus on making the profile discoverable by recruiters searching for "
        f"{', '.join(profile.get('target_roles', ['software engineer'])[:3])} roles.\n\n"
        "Format your response with clear sections and markdown."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a LinkedIn profile optimization expert."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=1000,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Error generating profile suggestions: {e}"
