#!@PORTAGE_BASH@

PYTHON_VERSIONS="2.6 2.7 3.1 3.2"

case "${NOCOLOR:-false}" in
	yes|true)
		GOOD=
		BAD=
		NORMAL=
		;;
	no|false)
		GOOD=$'\e[1;32m'
		BAD=$'\e[1;31m'
		NORMAL=$'\e[0m'
		;;
esac

exit_status="0"
for version in ${PYTHON_VERSIONS}; do
	if [[ -x @PORTAGE_PYTHON@${version} ]]; then
		echo -e "${GOOD}Testing with Python ${version}...${NORMAL}"
		if ! @PORTAGE_PYTHON@${version} pym/portage/tests/runTests; then
			echo -e "${BAD}Testing with Python ${version} failed${NORMAL}"
			exit_status="1"
		fi
		echo
	fi
done

exit ${exit_status}
