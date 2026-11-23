# Bash completion for towit.
_towit_completions() {
    local word="${COMP_WORDS[COMP_CWORD]}"
    local previous="${COMP_WORDS[COMP_CWORD-1]}"
    local subcommand="${COMP_WORDS[1]}"
    local flags choices prefix

    COMPREPLY=()
    if (( COMP_CWORD == 1 )); then
        choices='setup search list resume show prune forget export backfill install-hook
                 uninstall-hook teardown implode stats doctor version help -h --help -v --version'
        # shellcheck disable=SC2207  # mapfile needs bash 4; macOS ships 3.2, and compgen output has no spaces
        COMPREPLY=( $(compgen -W "$choices" -- "$word") )
        return 0
    fi

    case "$subcommand" in
        setup) flags='--full --hook --skill --config' ;;
        search) flags='--or --topic --all --summary --title --only --format --folder --repo --role --file' ;;
        list) flags='--format --folder --topic --keyword' ;;
        resume) flags='--force' ;;
        show) flags='--around --context --role --match --format' ;;
        prune) flags='--archive --yes --dry-run' ;;
        forget) flags='--repo --folder --yes -y' ;;
        export) flags='--topic --format --summarize' ;;
        backfill) flags='--dry-run --force --folder' ;;
        install-hook|uninstall-hook|stats|doctor) flags='' ;;
        teardown) flags='--yes -y' ;;
        implode) flags='--yes -y --install-dir' ;;
        *) return 0 ;;
    esac

    prefix=''
    if [[ $word == --*=* ]]; then
        previous=${word%%=*}
        prefix="$previous="
        word=${word#*=}
    elif [[ $previous == = && $COMP_CWORD -gt 2 ]]; then
        previous=${COMP_WORDS[COMP_CWORD-2]}
    fi

    case "$subcommand:$previous" in
        search:--format|list:--format) choices='json csv' ;;
        show:--format) choices='text json' ;;
        export:--format) choices='md json' ;;
        search:--only) choices='text metadata' ;;
        search:--role|show:--role) choices='user assistant' ;;
        *) choices='' ;;
    esac

    if [[ -n $choices ]]; then
        local match
        for match in $(compgen -W "$choices" -- "$word"); do
            COMPREPLY+=("$prefix$match")
        done
    elif [[ -z $prefix ]]; then
        # shellcheck disable=SC2207  # mapfile needs bash 4; macOS ships 3.2, and compgen output has no spaces
        COMPREPLY=( $(compgen -W "-h --help $flags" -- "$word") )
    fi
    return 0
}

complete -F _towit_completions towit
