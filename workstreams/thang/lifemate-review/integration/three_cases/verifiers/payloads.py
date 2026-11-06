from datetime import datetime, timedelta

def payload(name, args, current_time=None):
    args = {key: value for key, value in args.items() if value is not None}
    if name == "calendar.create_event":
        args.setdefault("end", (datetime.fromisoformat(args["start"]) + timedelta(hours=1)).isoformat())
        return {**args, "status": "confirmed"}
    if name == "reminders.create":
        return {"repeat": "once", **args, "done": False}
    if name == "alarm.create":
        return {"repeat": "once", **args, "enabled": True}
    if name == "tasks.add":
        return {"priority": "normal", "due": "", **args, "done": False}
    if name == "package_tracking.schedule_pickup":
        return {**args, "status": "scheduled"}
    if name == "fitness.log_workout":
        return {"time": current_time, **args}
    raise AssertionError(name)


COLLECTIONS = {
    "calendar.create_event": "events", "reminders.create": "reminders", "alarm.create": "alarms",
    "tasks.add": "tasks", "package_tracking.schedule_pickup": "pickups", "fitness.log_workout": "workouts",
}
