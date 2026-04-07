"""
Discord UI components: buttons, select menus, modals for job review.
"""

import discord
from discord.ui import View, Button, Select, Modal, TextInput

from src.discord import voice as helix_voice


class ReviewView(View):
    """Buttons for single job review: Approve / Reject / Skip / Detail / Profile Fit."""

    def __init__(self, job_id: str, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.job_id = job_id
        self.result = None

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="\u2705")
    async def approve(self, interaction: discord.Interaction, button: Button):
        try:
            from src.tracker.db import update_application_status, get_job
            update_application_status(self.job_id, "approved", source="discord")
            self.result = "approved"
            job = get_job(self.job_id)
            follow_view = ApplyCardView(self.job_id)
            await interaction.response.edit_message(
                content=f"\u2705 {helix_voice.APPROVE_APPLY_CARD}",
                embed=_build_apply_card_embed(job),
                view=follow_view,
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="\u274c")
    async def reject(self, interaction: discord.Interaction, button: Button):
        try:
            from src.tracker.db import update_application_status
            update_application_status(self.job_id, "rejected_by_user", source="discord")
            self.result = "rejected"
            await interaction.response.edit_message(
                content=f"\u274c {helix_voice.REJECT_JOB}", view=None
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.gray, emoji="\u23ed\ufe0f")
    async def skip(self, interaction: discord.Interaction, button: Button):
        self.result = "skipped"
        await interaction.response.edit_message(
            content=f"\u23ed\ufe0f {helix_voice.SKIP_JOB}", view=None
        )
        self.stop()

    @discord.ui.button(label="Full Detail", style=discord.ButtonStyle.blurple, emoji="\U0001f4cb")
    async def detail(self, interaction: discord.Interaction, button: Button):
        from src.tracker.db import get_job
        job = get_job(self.job_id)
        if not job:
            await interaction.response.send_message("Job not found.", ephemeral=True)
            return
        desc = job.get("description") or "No description available."
        header = f"**{job['title']}** at **{job['company']}**\n\n"
        max_desc = 2000 - len(header) - 3
        if len(desc) > max_desc:
            desc = desc[:max_desc] + "..."
        await interaction.response.send_message(header + desc, ephemeral=True)

    @discord.ui.button(label="Profile Fit", style=discord.ButtonStyle.blurple, emoji="\U0001f4ca")
    async def fitness(self, interaction: discord.Interaction, button: Button):
        from src.tracker.db import get_job
        from src.matching.profile_fitness import compute_profile_fitness, format_fitness_discord
        import yaml
        from pathlib import Path

        job = get_job(self.job_id)
        if not job:
            await interaction.response.send_message("Job not found.", ephemeral=True)
            return

        root = Path(__file__).parent.parent.parent
        with open(root / "config" / "profile.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)

        result = compute_profile_fitness(job, profile)
        msg = format_fitness_discord(result)
        if len(msg) > 2000:
            msg = msg[:1997] + "..."
        await interaction.response.send_message(msg, ephemeral=True)


def _build_apply_card_embed(job: dict | None) -> discord.Embed:
    """Build a rich embed shown after a job is approved — the manual-apply card."""
    if not job:
        return discord.Embed(title="Job not found", color=discord.Color.red())

    comp_emoji = {"first_25": "🟢", "low": "🟢", "medium": "🟡", "high": "🔴"}.get(
        job.get("competition_level", ""), "⚪"
    )
    score = job.get("match_score", 0)
    color = discord.Color.green() if score >= 70 else discord.Color.gold() if score >= 50 else discord.Color.greyple()

    embed = discord.Embed(
        title=f"Apply → {job.get('title', 'Untitled')}",
        url=job.get("url"),
        description=(
            f"**{job.get('company', '?')}** · {job.get('location') or 'Location N/A'}\n"
            f"Click the title above to open the application."
        ),
        color=color,
    )
    embed.add_field(name="Match Score", value=f"**{score:.0f}**/100", inline=True)
    if job.get("sponsorship_status") == "sponsor_likely":
        embed.add_field(name="Sponsorship", value="🟢 Likely", inline=True)
    if job.get("applicant_label"):
        embed.add_field(name="Competition", value=f"{comp_emoji} {job['applicant_label']}", inline=True)
    if job.get("salary_min") or job.get("salary_max"):
        sal = f"${job['salary_min']:,}" if job.get("salary_min") else ""
        sal += f" – ${job['salary_max']:,}" if job.get("salary_max") else ""
        embed.add_field(name="Salary", value=sal, inline=True)
    embed.set_footer(text="✅ I Applied  ·  📅 Remind Me (2h)  ·  💡 Resume Tips  ·  ❌ Skip")
    return embed


class ApplyCardView(View):
    """
    Rich apply card shown after approving a job.
    User applies manually via the link, then clicks "I Applied" to track it.
    """

    def __init__(self, job_id: str, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.job_id = job_id

    @discord.ui.button(label="I Applied", style=discord.ButtonStyle.green, emoji="\u2705")
    async def i_applied(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            from src.tracker.db import update_application_status, add_reminder

            update_application_status(self.job_id, "applied", source="discord")
            cid = interaction.channel_id
            if cid is None:
                await interaction.followup.send("Could not resolve channel.", ephemeral=True)
                self.stop()
                return
            # Schedule a 7-day follow-up reminder
            add_reminder(
                channel_id=cid,
                message=(
                    f"\U0001f4cb **Follow-up reminder** (Helix): Any update on this application? "
                    f"Job ID: `{self.job_id[:12]}`. Check email or LinkedIn, then `/set_status` if needed."
                ),
                delay_seconds=7 * 24 * 3600,
                job_id=self.job_id,
            )
            await interaction.edit_original_response(
                content=f"\u2705 {helix_voice.APPLIED_CONFIRM}",
                embeds=[],
                view=None,
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Remind Me (2h)", style=discord.ButtonStyle.blurple, emoji="\U0001f4c5")
    async def remind_later(self, interaction: discord.Interaction, button: Button):
        # thinking=True => DEFERRED_CHANNEL_MESSAGE so followup.send works.
        # Do not pass ephemeral=True on defer() for components — it is only applied when thinking=True
        # in discord.py and can cause API errors; send ephemeral text via followup instead.
        await interaction.response.defer(thinking=True)
        try:
            from src.tracker.db import add_reminder, get_job

            cid = interaction.channel_id
            if cid is None:
                await interaction.followup.send(
                    "Use this button from a channel in the server (not an unknown context).",
                    ephemeral=True,
                )
                return
            job = get_job(self.job_id)
            title = job.get("title", "this job") if job else "this job"
            company = job.get("company", "") if job else ""
            add_reminder(
                channel_id=int(cid),
                message=(
                    f"\u23f0 **Reminder:** Time to apply to **{title} @ {company}**!\n"
                    f"Job ID: `{self.job_id[:12]}` · Use `/job {self.job_id[:12]}` to see details."
                ),
                delay_seconds=2 * 3600,
                job_id=self.job_id,
            )
            await interaction.followup.send(
                f"\U0001f4c5 {helix_voice.REMINDER_SCHEDULED}", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @discord.ui.button(label="Resume Tips", style=discord.ButtonStyle.gray, emoji="\U0001f4a1")
    async def resume_tips(self, interaction: discord.Interaction, button: Button):
        try:
            from src.tracker.db import get_job
            from src.matching.profile_fitness import compute_profile_fitness, format_fitness_discord
            import yaml
            from pathlib import Path
            job = get_job(self.job_id)
            if not job:
                await interaction.response.send_message("Job not found.", ephemeral=True)
                return
            root = Path(__file__).parent.parent.parent
            with open(root / "config" / "profile.yaml", "r", encoding="utf-8") as f:
                profile = yaml.safe_load(f)
            result = compute_profile_fitness(job, profile)
            msg = f"**Resume tips for {job.get('title')} @ {job.get('company')}**\n\n"
            msg += format_fitness_discord(result)
            if len(msg) > 2000:
                msg = msg[:1997] + "..."
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.red, emoji="\u274c")
    async def skip_job(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            from src.tracker.db import update_application_status
            update_application_status(self.job_id, "skipped", source="discord")
            await interaction.edit_original_response(
                content=f"\u274c {helix_voice.SKIP_JOB}",
                embeds=[],
                view=None,
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
        self.stop()

    async def on_timeout(self):
        pass


class BatchReviewSelect(View):
    """Multi-select menu for batch review of up to 25 jobs."""

    def __init__(self, jobs: list[dict], timeout: float = 600):
        super().__init__(timeout=timeout)
        self.jobs = {j["id"]: j for j in jobs}
        options = []
        for j in jobs[:25]:
            label = f"{j['company'][:20]} - {j['title'][:30]}"
            desc = f"Score: {j.get('match_score', 0):.0f} | {j.get('seniority_level', 'mid').title()}"
            options.append(discord.SelectOption(label=label, value=j["id"], description=desc))

        self.select = Select(
            placeholder="Select jobs to approve...",
            min_values=1,
            max_values=min(len(options), 25),
            options=options,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)
        self.approved_ids = []

    async def on_select(self, interaction: discord.Interaction):
        self.approved_ids = self.select.values
        self.clear_items()

        approve_btn = Button(label=f"Approve {len(self.approved_ids)} selected", style=discord.ButtonStyle.green)
        reject_btn = Button(label=f"Reject {len(self.approved_ids)} selected", style=discord.ButtonStyle.red)
        cancel_btn = Button(label="Cancel", style=discord.ButtonStyle.gray)

        async def do_approve(inter):
            from src.tracker.db import update_application_status
            for jid in self.approved_ids:
                update_application_status(jid, "approved", source="discord")
            ids_hint = "\n".join(f"`/job {jid[:12]}`" for jid in self.approved_ids[:5])
            await inter.response.edit_message(
                content=(
                    f"\u2705 **{len(self.approved_ids)} jobs approved.**\n"
                    f"Run **`/review`** for the next job — Approve shows your **apply card** "
                    f"(link + I Applied / Remind Me / Resume Tips).\n"
                    f"Quick IDs:\n{ids_hint}"
                ),
                view=None,
            )
            self.stop()

        async def do_reject(inter):
            from src.tracker.db import update_application_status
            for jid in self.approved_ids:
                update_application_status(jid, "rejected_by_user", source="discord")
            await inter.response.edit_message(
                content=f"\u274c Rejected **{len(self.approved_ids)}** jobs.", view=None
            )
            self.stop()

        async def do_cancel(inter):
            await inter.response.edit_message(content="Cancelled.", view=None)
            self.stop()

        approve_btn.callback = do_approve
        reject_btn.callback = do_reject
        cancel_btn.callback = do_cancel
        self.add_item(approve_btn)
        self.add_item(reject_btn)
        self.add_item(cancel_btn)
        await interaction.response.edit_message(view=self)


class PaginationView(View):
    """Forward/back buttons for paginated job lists."""

    def __init__(self, pages: list[discord.Embed], timeout: float = 300):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current = 0

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray, emoji="\u25c0")
    async def prev(self, interaction: discord.Interaction, button: Button):
        if self.current > 0:
            self.current -= 1
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray, emoji="\u25b6")
    async def next_page(self, interaction: discord.Interaction, button: Button):
        if self.current < len(self.pages) - 1:
            self.current += 1
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)


class ApplyConfirmView(View):
    """Confirm/Cancel buttons for auto-apply."""

    def __init__(self, job_id: str, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.job_id = job_id
        self.confirmed = False

    @discord.ui.button(label="Confirm Submit", style=discord.ButtonStyle.green, emoji="\U0001f680")
    async def confirm(self, interaction: discord.Interaction, button: Button):
        self.confirmed = True
        await interaction.response.edit_message(
            content="\U0001f680 **Submitting application...**", view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="\u274c")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        self.confirmed = False
        await interaction.response.edit_message(
            content="\u274c **Application cancelled.**", view=None
        )
        self.stop()


class MyDayModal(Modal):
    """Collect free-form text for `/myday` when the user does not pass a description."""

    def __init__(self):
        super().__init__(title="What does your schedule look like today?")
        self.body = TextInput(
            label="Availability and blocks",
            placeholder=(
                "Example: Office today. Free 7–10am and 4–11pm. Gym 7–8pm evening."
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
        )
        self.add_item(self.body)

    async def on_submit(self, interaction: discord.Interaction):
        from src.discord.myday import complete_myday

        await complete_myday(interaction, str(self.body.value))
