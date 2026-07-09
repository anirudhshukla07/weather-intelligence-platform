import { useEffect, useState } from "react";

const DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

function pad(n) {
  return String(n).padStart(2, "0");
}

export default function Clock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="topbar-clock" title="Current system date and time">
      <strong>
        {pad(now.getHours())}:{pad(now.getMinutes())}:{pad(now.getSeconds())}
      </strong>
      <span>
        {DOW[now.getDay()]} · {MONTHS[now.getMonth()]} {now.getDate()},{" "}
        {now.getFullYear()}
      </span>
    </div>
  );
}
