#!/usr/bin/env bash
# Claude Code statusline: one jq call, one git call (cached per directory).
# Requires: bash 3.2+, jq 1.6+, git 2.11+. Works on macOS and Linux.
# Set "refreshInterval": 60 in the statusLine settings so the reset countdowns
# keep ticking while the session is idle.

# --- Parse everything in a single jq pass -----------------------------------
# Fields are joined with \x1f (unit separator) so empty values survive `read`.
DATA=$(jq -r '
  def clean: tostring | gsub("[\u0000-\u001f\u007f-\u009f]"; "");  # no terminal escapes
  def tok: if . >= 1000000 then "\((. / 100000 | floor) / 10)M"
           elif . >= 1000 then "\((. / 100 | floor) / 10)k"
           else tostring end;
  def dur: (. / 1000 | floor) as $s
           | if $s >= 3600 then "\($s / 3600 | floor)h\($s % 3600 / 60 | floor)m"
             elif $s >= 60 then "\($s / 60 | floor)m"
             else "\($s)s" end;
  def left: (. - now | floor) as $s
            | if $s <= 0 then ""
              elif $s < 60 then "<1m"
              elif $s < 3600 then "\($s / 60 | floor)m"
              elif $s < 86400 then "\($s / 3600 | floor)h\($s % 3600 / 60 | floor)m"
              else "\($s / 86400 | floor)d\($s % 86400 / 3600 | floor)h" end;
  def cells($n): [range($n) | "━"] | join("");
  def pct: [[(.context_window.used_percentage // 0 | floor), 0] | max, 100] | min;
  # Rate-limit window: percentage, countdown, and a pace colour. Pace compares
  # the share of the limit used with the share of the window gone: using it
  # faster than time passes means it runs out before the reset.
  def lim($k; $win): .rate_limits[$k] as $l
    | if ($l.used_percentage // null) == null then "", "", ""
      else ($l.used_percentage) as $u
        | (if $l.resets_at then ([[1 - (($l.resets_at - now) / $win), 0] | max, 1] | min)
           else null end) as $gone
        | (if $u >= 90 then "R"
           elif $gone == null or $gone < 0.1 then ""
           elif $u / 100 / $gone >= 1.25 then "R"
           elif $u / 100 / $gone >= 1 then "Y"
           else "" end) as $pace
        | "\($u | round)", $pace, ($l.resets_at // 0 | if . > 0 then left else "" end)
      end;
  [ (.model.display_name // "unknown" | clean),
    (.effort.level // "" | clean),
    (.fast_mode // false),
    (.session_name // "" | clean),
    (.agent.name // "" | clean),
    (.vim.mode // "" | clean),
    (.output_style.name // "default" | clean),
    (.workspace.current_dir // "" | clean),
    (.workspace.project_dir // "" | clean),
    (.workspace.added_dirs // [] | length),
    (.workspace.git_worktree // "" | clean),
    (pct),
    (pct / 10 | floor | cells(.)),
    (pct / 10 | floor | cells(10 - .)),
    (.context_window.context_window_size // 200000 | tok),
    (.context_window.total_input_tokens // 0 | tok),
    (.context_window.total_output_tokens // 0 | tok),
    ((.cost.total_cost_usd // 0) * 100 | round
       | "\(. / 100 | floor).\(. % 100 | tostring | if length < 2 then "0" + . else . end)"),
    (.rate_limits.five_hour or .rate_limits.seven_day),
    (.cost.total_duration_ms // 0 | dur),
    (.cost.total_lines_added // 0),
    (.cost.total_lines_removed // 0),
    (.exceeds_200k_tokens // false),
    lim("five_hour"; 18000),
    lim("seven_day"; 604800)
  ] | map(tostring) | join("\u001f")' 2>/dev/null) && [ -n "$DATA" ] \
  || { echo "statusline: unreadable input"; exit 0; }
IFS=$'\x1f' read -r MODEL EFFORT FAST SESSION AGENT VIM STYLE DIR PROJ ADDED WT \
  PCT BAR_ON BAR_OFF CTX TOK_IN TOK_OUT COST SUB DUR ADD DEL OVER \
  L5 L5C L5T L7 L7C L7T <<< "$DATA"

# --- Colors & icons (hex UTF-8 bytes: portable to macOS bash 3.2) -----------
# Icons are monochrome text symbols, not emoji, so they take the colour of the
# text around them and stay one cell wide.
C=$'\e[36m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' M=$'\e[35m' B=$'\e[34m'
D=$'\e[2m' BOLD=$'\e[1m' X=$'\e[0m'
I_DIR=$'\xe2\x8c\x82'   # ⌂
I_GIT=$'\xe2\x8e\x87'   # ⎇
I_TAG=$'\xe2\x97\x87'   # ◇
I_BOT=$'\xe2\x97\x86'   # ◆
I_WARN=$'\xe2\x96\xb2'  # ▲
I_TIME=$'\xe2\x97\xb7'  # ◷
I_RESET=$'\xe2\x86\xbb' # ↻

# --- Git: one `git status` call, cached 5s per directory --------------------
git_info() {
  local dir=${DIR:-$PWD} now cache key ts
  now=$(date +%s)
  key=$(printf '%s' "$dir" | cksum)
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline/${key%% *}"
  if [ -f "$cache" ]; then
    IFS='|' read -r ts BRANCH STAGED MODIFIED < "$cache"
    [ $((now - ${ts:-0})) -le 5 ] && return
  fi
  # porcelain v2: "1 XY ..." / "2 XY ..." entries; X=index, Y=worktree ('.' = clean).
  # "u ..." is a merge conflict: counted once as staged and once as modified.
  # A detached HEAD shows no branch, like `git branch --show-current`.
  IFS='|' read -r BRANCH STAGED MODIFIED < <(
    git -C "$dir" status --porcelain=v2 --branch 2>/dev/null | awk '
      /^# branch.head / { if ($3 != "(detached)") b = $3 }
      /^[12] /          { if (substr($2,1,1) != ".") s++; if (substr($2,2,1) != ".") m++ }
      /^u /             { s++; m++ }
      END               { printf "%s|%d|%d\n", b, s, m }')
  mkdir -p "${cache%/*}" && printf '%s|%s|%s|%s\n' "$now" "$BRANCH" "$STAGED" "$MODIFIED" > "$cache"
}
git_info

# --- Layout: drop the least important segments when the terminal is narrow --
# Each segment is "PRIORITY:TEXT". Priority 0 never drops; higher drops first.
# Claude Code sets COLUMNS to the terminal width; without it nothing drops.
SEP='  '
fit() {
  local max=$(( ${COLUMNS:-0} - 4 )) i n=0 total worst plain c
  local -a pri txt wid
  for i in "$@"; do
    pri[n]=${i%%:*} txt[n]=${i#*:}
    plain=${txt[n]}
    for c in "$C" "$G" "$Y" "$R" "$M" "$B" "$D" "$BOLD" "$X"; do plain=${plain//"$c"/}; done
    wid[n]=${#plain} n=$((n + 1))
  done
  while [ "$max" -gt 0 ]; do
    total=0 worst=-1
    for ((i = 0; i < n; i++)); do
      [ -n "${txt[i]}" ] || continue
      total=$((total + wid[i] + ${#SEP}))
      [ "${pri[i]}" -gt 0 ] && { [ "$worst" -lt 0 ] || [ "${pri[i]}" -gt "${pri[worst]}" ]; } && worst=$i
    done
    [ $((total - ${#SEP})) -le "$max" ] || [ "$worst" -lt 0 ] && break
    txt[worst]=''
  done
  LINE=''
  for ((i = 0; i < n; i++)); do
    [ -n "${txt[i]}" ] && LINE+="${LINE:+$SEP}${txt[i]}"
  done
}

# --- Line 1: who, where ------------------------------------------------------
S_MODEL="$C$BOLD$MODEL$X"
[ -n "$EFFORT" ]     && S_MODEL+=" $D· $EFFORT$X"
[ "$FAST" = true ]   && S_MODEL+=" $Y· fast$X"
S_AGENT='' S_VIM='' S_STYLE='' S_SESSION='' S_PROJ='' S_ADDED='' S_GIT=''
[ -n "$AGENT" ]      && S_AGENT="$Y$I_BOT $AGENT$X"
[ -n "$VIM" ]        && S_VIM="$B[$VIM]$X"
[ "$STYLE" != default ] && S_STYLE="${D}style:$STYLE$X"
[ -n "$SESSION" ]    && S_SESSION="$M$I_TAG $SESSION$X"
SHOWN_DIR=${DIR:-?}
S_DIR="$I_DIR ${SHOWN_DIR##*/}"
[ -n "$PROJ" ] && [ "$DIR" != "$PROJ" ] && S_PROJ="$D(proj: ${PROJ##*/})$X"
[ "$ADDED" -gt 0 ]   && S_ADDED="$D+$ADDED dirs$X"
if [ -n "$BRANCH" ]; then
  S_GIT="$I_GIT $BRANCH"
  [ -n "$WT" ]               && S_GIT+=" ${D}wt:$WT$X"
  [ "${STAGED:-0}" -gt 0 ]   && S_GIT+=" $G+$STAGED$X"
  [ "${MODIFIED:-0}" -gt 0 ] && S_GIT+=" $Y~$MODIFIED$X"
fi
fit "0:$S_MODEL" "3:$S_AGENT" "2:$S_VIM" "6:$S_STYLE" "4:$S_SESSION" \
    "0:$S_DIR" "5:$S_PROJ" "7:$S_ADDED" "1:$S_GIT"
L1=$LINE

# --- Line 2: how much is left ------------------------------------------------
# The bar is always coloured; the percentage only when it needs attention.
if   [ "$PCT" -ge 90 ]; then BC=$R PC=$R
elif [ "$PCT" -ge 70 ]; then BC=$Y PC=$Y
else BC=$G PC=''; fi
S_CTX="$BC$BAR_ON$X$D$BAR_OFF$X $PC$PCT%$X ${D}of $CTX$X"
[ "$OVER" = true ] && S_CTX+=" $R$I_WARN >200k$X"
S_TOK="${D}in:$X$TOK_IN ${D}out:$X$TOK_OUT"
limit() {  # limit LABEL PERCENT PACE COUNTDOWN
  local col=''
  case $3 in R) col=$R ;; Y) col=$Y ;; esac
  LIM=''
  [ -n "$2" ] || return
  LIM="$D$1$X $col$2%$X"
  [ -n "$4" ] && LIM+=" $D$I_RESET $4$X"
}
limit 5h "$L5" "$L5C" "$L5T"; S_L5=$LIM
limit 7d "$L7" "$L7C" "$L7T"; S_L7=$LIM
# Subscribers pay a flat fee, so the cost is a list-price estimate: dimmed and
# marked with ~. Pay-as-you-go users see it at full strength.
if [ "$SUB" = true ]; then S_COST="$D~\$$COST$X"; else S_COST="\$$COST"; fi
S_TIME="$D$I_TIME $DUR$X"
S_LINES="$G+$ADD$X $R-$DEL$X"
fit "0:$S_CTX" "3:$S_TOK" "0:$S_L5" "4:$S_L7" "2:$S_COST" "6:$S_TIME" "5:$S_LINES"
L2=$LINE

printf '%s\n%s\n' "$L1" "$L2"
