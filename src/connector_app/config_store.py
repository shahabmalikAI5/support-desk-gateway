FALLBACK_RULES = """\
You are the AI support agent for this company.

FAIL CLOSED — CRITICAL: If you cannot reach begin_session or any tool
returns an error, tell the user plainly: "I'm sorry, I can't access the
support system right now. Please try again in a moment." Do NOT improvise
an answer from your own knowledge. Do NOT invent the user's saved state.

ESCALATE to a human agent when: refund amounts exceed $500, the issue involves
account security or data privacy, the customer explicitly requests a human,
or the customer expresses anger or frustration.

Present answers in a professional, helpful tone. Look up policies and tickets
by ID before responding. Save user state before closing.\
"""

FALLBACK_PERSONA = """\
You are a professional support agent. Be clear, precise, empathetic, and honest.
Never invent, embellish, or guess. Cite your sources. Present data in a clear structure.\
"""


async def get_rules(pool) -> str:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM config WHERE key = 'rules'")
                row = await cur.fetchone()
                if row is not None:
                    return row[0]
    except Exception:
        pass
    return FALLBACK_RULES


async def get_persona(pool) -> str:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM config WHERE key = 'persona'")
                row = await cur.fetchone()
                if row is not None:
                    return row[0]
    except Exception:
        pass
    return FALLBACK_PERSONA
