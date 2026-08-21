/* FullCalendar setup for the squad calendar (request-builder) page. Weekends
 * are hidden entirely (see weekends: false below) - nobody works or takes
 * leave on a Saturday/Sunday, so the columns carry no information. */

function formatLocalDate(date) {
  var y = date.getFullYear();
  var m = String(date.getMonth() + 1).padStart(2, "0");
  var d = String(date.getDate()).padStart(2, "0");
  return y + "-" + m + "-" + d;
}

function injectDaySummaries(calendarEl, events, titleTotals) {
  calendarEl.querySelectorAll(".day-working-summary").forEach(function (el) {
    el.remove();
  });
  if (!titleTotals) return;

  var absentByDateTitle = {};
  events.forEach(function (ev) {
    var props = ev.extendedProps || {};
    // Only APPROVED, full-day absences reduce the "working" headcount - a
    // pending request isn't confirmed yet, and a half-day absentee is still
    // working part of the day.
    if (props.type !== "holiday" || props.status !== "approved" || props.dayPart !== "full") return;
    var dateStr = ev.startStr.slice(0, 10);
    absentByDateTitle[dateStr] = absentByDateTitle[dateStr] || {};
    absentByDateTitle[dateStr][props.titleCode] = (absentByDateTitle[dateStr][props.titleCode] || 0) + 1;
  });

  calendarEl.querySelectorAll(".fc-daygrid-day").forEach(function (cell) {
    var dateStr = cell.getAttribute("data-date");
    if (!dateStr) return;
    var frame = cell.querySelector(".fc-daygrid-day-frame");
    if (!frame) return;
    var absentToday = absentByDateTitle[dateStr] || {};
    var summary = document.createElement("div");
    summary.className = "day-working-summary";
    var rendered = 0;
    Object.keys(titleTotals).forEach(function (code) {
      var total = titleTotals[code].total;
      if (!total) return;
      var absent = absentToday[code] || 0;
      var working = Math.max(total - absent, 0);
      if (rendered) summary.appendChild(document.createTextNode(" · "));
      // Titles that are short-staffed today are the whole point of this
      // row, so they get picked out rather than blending into the list.
      var part = document.createElement("span");
      if (absent) part.className = "away";
      part.textContent = titleTotals[code].abbreviation + " " + working + "/" + total;
      summary.appendChild(part);
      rendered += 1;
    });
    if (!rendered) return;
    frame.appendChild(summary);
  });
}

/**
 * opts:
 *   elementId: DOM id of the calendar container
 *   feedUrl: calendar-feed JSON endpoint
 *   selectable: whether clicking a weekday cycles it through full/half/none
 *   titleTotals: {code: {label, abbreviation, total}} for the per-day working summary, or null to skip it
 *   onSelectionChange: function(selectedDays) called after each click, selectedDays is {dateStr: "full"|"half"}
 *   onSilentDayClick: function(dateStr) called when a day is clicked while silent-edit mode is active
 *     (see returned setSilentMode below) - owns all of silentDays' state entirely (see
 *     squad_calendar.html: it fetches the selected member's current status for that date and cycles
 *     through only the transitions that make sense from there), the widget just re-renders afterward.
 *
 * Silent-edit mode and the normal request-builder selection are mutually
 * exclusive per click (silent-edit wins while active) since they serve
 * different people/purposes but share the same calendar and click handler.
 */
function initSquadCalendar(opts) {
  var selectedDays = {};
  var silentDays = {};
  var silentModeActive = false;
  var onSelectionChange = opts.onSelectionChange || function () {};
  var calendarEl = document.getElementById(opts.elementId);

  var calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: "dayGridMonth",
    height: "auto",
    firstDay: 1, // Monday first
    weekends: false, // weekends carry no work/absence information, so drop the columns entirely
    dayMaxEvents: false, // never truncate with "+N more" - every absentee must show
    events: opts.feedUrl,
    dayCellClassNames: function (arg) {
      var classes = [];
      if (opts.selectable) {
        var part = selectedDays[formatLocalDate(arg.date)];
        if (part === "full") classes.push("selected-full-day");
        if (part === "half") classes.push("selected-half-day");
      }
      var silentEntry = silentDays[formatLocalDate(arg.date)];
      if (silentEntry) {
        // Hashed either way (add or cancel) - only day_part decides how much
        // of the cell it covers, so a half day is never shown as a full one.
        classes.push("silent-edit-" + silentEntry.day_part);
      }
      return classes;
    },
    dateClick: function (info) {
      handleDayClick(info.dateStr);
    },
    // A day that already shows a holiday event renders that event as its
    // own clickable element inside the cell, which swallows the click
    // before it reaches dateClick above - exactly the day you'd want to
    // click to cancel it. Routing eventClick through the same handler
    // means clicking either the empty cell or the event chip works.
    eventClick: function (info) {
      if (!silentModeActive) return;
      info.jsEvent.preventDefault();
      handleDayClick(formatLocalDate(info.event.start));
    },
    eventsSet: function (events) {
      injectDaySummaries(calendarEl, events, opts.titleTotals);
    },
  });

  function handleDayClick(dateStr) {
    var isBankHoliday = calendar.getEvents().some(function (ev) {
      var props = ev.extendedProps || {};
      return props.type === "bankholiday" && formatLocalDate(ev.start) === dateStr;
    });
    if (isBankHoliday) return; // can't request/edit a bank holiday

    if (silentModeActive) {
      if (opts.onSilentDayClick) opts.onSilentDayClick(dateStr);
      calendar.render();
      return;
    }

    if (!opts.selectable) return;
    var current = selectedDays[dateStr];
    if (!current) {
      selectedDays[dateStr] = "full"; // click 1: full day
    } else if (current === "full") {
      selectedDays[dateStr] = "half"; // click 2: half day
    } else {
      delete selectedDays[dateStr]; // click 3: back to unselected
    }
    onSelectionChange(selectedDays);
    calendar.render();
  }

  calendar.render();
  return {
    calendar: calendar,
    selectedDays: selectedDays,
    silentDays: silentDays,
    setSilentMode: function (active) {
      silentModeActive = active;
    },
  };
}
