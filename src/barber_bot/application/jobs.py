"""Фоновые use cases: «будильник» в базе вместо планировщика (см. spec, «Фоновые задачи»)."""

from barber_bot.application.context import AppContext, load_details
from barber_bot.application.notifications import DailySummary, Reminder


class BackgroundJobs:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def send_due_reminders(self) -> int:
        """Отправляет наступившие напоминания; возвращает, сколько ушло клиентам."""
        ctx = self._ctx
        sent = 0
        async with ctx.uow() as uow:
            due = await uow.appointments.due_reminders(ctx.clock.now())
            batch = [await load_details(uow, a) for a in due]
        for details in batch:
            telegram_id = details.client.telegram_id
            if telegram_id is not None:
                await ctx.notify(Reminder(telegram_id, details))
                sent += 1
            # Отметку ставим после попытки: повтор возможен, только если процесс упал между ними.
            async with ctx.uow() as uow:
                appointment = await uow.appointments.get(details.appointment.id or 0)
                if appointment is not None and not appointment.reminder_sent:
                    appointment.reminder_sent = True
                    await uow.appointments.update(appointment)
                    await uow.commit()
        return sent

    async def send_daily_summary(self) -> bool:
        """Отправляет сводку дня, если пора и за сегодня её ещё не было. True — отправлена."""
        ctx = self._ctx
        now = ctx.clock.now()
        if now.time() < ctx.rules.summary_time:
            return False
        today = now.date()
        async with ctx.uow() as uow:
            if await uow.summaries.was_sent(today):
                return False
            start, end = ctx.day_bounds(today)
            appointments = [
                await load_details(uow, a)
                for a in await uow.appointments.active_between(start, end)
            ]
            await uow.summaries.mark_sent(today, now)
            await uow.commit()
        if not appointments:
            return False
        await ctx.notify(DailySummary(today, appointments))
        return True
