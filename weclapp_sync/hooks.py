from . import __version__ as app_version

app_name = "weclapp_sync"
app_title = "WeClapp Sync"
app_publisher = "Marcel Ulber"
app_description = "WeClapp → ERPNext live sync (full import + scheduled delta sync)"
app_email = "drdothouse@gmail.com"
app_license = "MIT"
required_apps = ["frappe/erpnext"]

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Der Delta-Sync läuft NICHT direkt im Scheduler-Tick, sondern der Tick prüft nur, ob laut
# "WeClapp Settings" ein Lauf fällig ist, und enqueued dann einen langlaufenden Background-Job.
# So bleibt der Scheduler-Worker frei und ein hängender WeClapp-Request blockiert ihn nicht.
scheduler_events = {
	"cron": {
		# Jede Minute prüfen, ob ein Delta-Sync fällig ist (Intervall steht in den Settings).
		"* * * * *": [
			"weclapp_sync.sync.scheduler.enqueue_due_delta_sync",
		],
	},
	"hourly_long": [
		# Sicherheitsnetz: Läufe, die laut Log noch "running" sind, deren Worker aber
		# weg ist (OOM/Neustart), wieder als abgebrochen markieren.
		"weclapp_sync.sync.scheduler.recover_stale_runs",
	],
}

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
after_install = "weclapp_sync.install.after_install"

# ---------------------------------------------------------------------------
# Fixtures (Custom Fields etc., die der Sync auf ERPNext-Standard-Doctypes braucht -
# z.B. wc_id / wc_last_synced auf Customer, Item, Sales Invoice, ...)
# TODO: befüllen, sobald die Mapper feststehen (siehe reference/setup.py Custom-Field-Teil).
# ---------------------------------------------------------------------------
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["name", "like", "%-wc_%"]],
	},
]
