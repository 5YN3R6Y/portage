#!@PORTAGE_BASH@
# Copyright 1999-2009 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2
# $Id$
#
# Miscellaneous shell functions that make use of the ebuild env but don't need
# to be included directly in ebuild.sh.
#
# We're sourcing ebuild.sh here so that we inherit all of it's goodness,
# including bashrc trickery.  This approach allows us to do our miscellaneous
# shell work withing the same env that ebuild.sh has, but without polluting
# ebuild.sh itself with unneeded logic and shell code.
#
# XXX hack: clear the args so ebuild.sh doesn't see them
MISC_FUNCTIONS_ARGS="$@"
shift $#

source @PORTAGE_BASE@/bin/ebuild.sh

install_symlink_html_docs() {
	cd "${D}" || die "cd failed"
	[[ ! -d ${ED} ]] && dodir /
	cd "${ED}" || die "cd shouldn't have failed"
	#symlink the html documentation (if DOC_SYMLINKS_DIR is set in make.conf)
	if [ -n "${DOC_SYMLINKS_DIR}" ] ; then
		local mydocdir docdir
		for docdir in "${HTMLDOC_DIR:-does/not/exist}" "${PF}/html" "${PF}/HTML" "${P}/html" "${P}/HTML" ; do
			if [ -d "usr/share/doc/${docdir}" ] ; then
				mydocdir="${EPREFIX}/usr/share/doc/${docdir}"
			fi
		done
		if [ -n "${mydocdir}" ] ; then
			local mysympath
			if [ -z "${SLOT}" -o "${SLOT}" = "0" ] ; then
				mysympath="${DOC_SYMLINKS_DIR}/${CATEGORY}/${PN}"
			else
				mysympath="${DOC_SYMLINKS_DIR}/${CATEGORY}/${PN}-${SLOT}"
			fi
			einfo "Symlinking ${mysympath} to the HTML documentation"
			dodir "${DOC_SYMLINKS_DIR}/${CATEGORY}"
			dosym "${mydocdir}" "${mysympath}"
		fi
	fi
}

install_qa_check() {
	cd "${D}" || die "cd failed"

	export STRIP_MASK
	prepall
	ecompressdir --dequeue
	ecompress --dequeue

	# Now we look for all world writable files.
	for i in $(find "${D}/" -type f -perm -2); do
		vecho -ne '\a'
		vecho "QA Security Notice:"
		vecho "- ${i:${#D}:${#i}} will be a world writable file."
		vecho "- This may or may not be a security problem, most of the time it is one."
		vecho "- Please double check that $PF really needs a world writeable bit and file bugs accordingly."
		sleep 1
	done

	# anything outside the prefix should be caught by the Prefix QA
	# check, so if there's nothing in ED, we skip searching for QA
	# checks there, the specific QA funcs can hence rely on ED existing
	if [[ -d ${ED} ]] ; then
		case ${CHOST} in
			*-darwin*)
				# Mach-O platforms (NeXT, Darwin, OSX)
				install_qa_check_macho
			;;
			*-interix*|*-winnt*)
				# PECOFF platforms (Windows/Interix)
				install_qa_check_pecoff
			;;
			*-aix*)
				# XCOFF platforms (AIX)
				install_qa_check_xcoff
			;;
			*)
				# because this is the majority: ELF platforms (Linux,
				# Solaris, *BSD, IRIX, etc.)
				install_qa_check_elf
			;;
		esac
	fi

	# this is basically here such that the diff with trunk remains just
	# offsetted and not out of order
	install_qa_check_misc

	# Prefix specific checks
	[[ -n ${EPREFIX} ]] && install_qa_check_prefix
}

install_qa_check_elf() {
	if type -P scanelf > /dev/null && ! hasq binchecks ${RESTRICT}; then
		local qa_var insecure_rpath=0 tmp_quiet=${PORTAGE_QUIET}
		local f x

		# display warnings when using stricter because we die afterwards
		if has stricter ${FEATURES} ; then
			unset PORTAGE_QUIET
		fi

		# Make sure we disallow insecure RUNPATH/RPATHs
		# Don't want paths that point to the tree where the package was built
		# (older, broken libtools would do this).  Also check for null paths
		# because the loader will search $PWD when it finds null paths.
		f=$(scanelf -qyRF '%r %p' "${D}" | grep -E "(${PORTAGE_BUILDDIR}|: |::|^:|^ )")
		# Reject set*id binaries with $ORIGIN in RPATH #260331
		x=$(
			find "${D}" -type f \( -perm -u+s -o -perm -g+s \) -print0 | \
			xargs -0 scanelf -qyRF '%r %p' | grep '$ORIGIN'
		)
		if [[ -n ${f}${x} ]] ; then
			vecho -ne '\a\n'
			eqawarn "QA Notice: The following files contain insecure RUNPATHs"
			eqawarn " Please file a bug about this at http://bugs.gentoo.org/"
			eqawarn " with the maintaining herd of the package."
			eqawarn "${f}${f:+${x:+\n}}${x}"
			vecho -ne '\a\n'
			if [[ -n ${x} ]] || has stricter ${FEATURES} ; then
				insecure_rpath=1
			else
				vecho "Auto fixing rpaths for ${f}"
				TMPDIR=${PORTAGE_BUILDDIR} scanelf -BXr ${f} -o /dev/null
			fi
		fi

		# TEXTRELs are baaaaaaaad
		# Allow devs to mark things as ignorable ... e.g. things that are
		# binary-only and upstream isn't cooperating (nvidia-glx) ... we
		# allow ebuild authors to set QA_TEXTRELS_arch and QA_TEXTRELS ...
		# the former overrides the latter ... regexes allowed ! :)
		qa_var="QA_TEXTRELS_${ARCH/-/_}"
		[[ -n ${!qa_var} ]] && QA_TEXTRELS=${!qa_var}
		[[ -n ${QA_STRICT_TEXTRELS} ]] && QA_TEXTRELS=""
		export QA_TEXTRELS="${QA_TEXTRELS} lib*/modules/*.ko"
		f=$(scanelf -qyRF '%t %p' "${D}" | grep -v 'usr/lib/debug/')
		if [[ -n ${f} ]] ; then
			scanelf -qyRAF '%T %p' "${PORTAGE_BUILDDIR}"/ &> "${T}"/scanelf-textrel.log
			vecho -ne '\a\n'
			eqawarn "QA Notice: The following files contain runtime text relocations"
			eqawarn " Text relocations force the dynamic linker to perform extra"
			eqawarn " work at startup, waste system resources, and may pose a security"
			eqawarn " risk.  On some architectures, the code may not even function"
			eqawarn " properly, if at all."
			eqawarn " For more information, see http://hardened.gentoo.org/pic-fix-guide.xml"
			eqawarn " Please include the following list of files in your report:"
			eqawarn "${f}"
			vecho -ne '\a\n'
			die_msg="${die_msg} textrels,"
			sleep 1
		fi

		# Also, executable stacks only matter on linux (and just glibc atm ...)
		f=""
		case ${CTARGET:-${CHOST}} in
			*-linux-gnu*)
			# Check for files with executable stacks, but only on arches which
			# are supported at the moment.  Keep this list in sync with
			# http://hardened.gentoo.org/gnu-stack.xml (Arch Status)
			case ${CTARGET:-${CHOST}} in
				arm*|i?86*|ia64*|m68k*|s390*|sh*|x86_64*)
					# Allow devs to mark things as ignorable ... e.g. things
					# that are binary-only and upstream isn't cooperating ...
					# we allow ebuild authors to set QA_EXECSTACK_arch and
					# QA_EXECSTACK ... the former overrides the latter ...
					# regexes allowed ! :)

					qa_var="QA_EXECSTACK_${ARCH/-/_}"
					[[ -n ${!qa_var} ]] && QA_EXECSTACK=${!qa_var}
					[[ -n ${QA_STRICT_EXECSTACK} ]] && QA_EXECSTACK=""
					qa_var="QA_WX_LOAD_${ARCH/-/_}"
					[[ -n ${!qa_var} ]] && QA_WX_LOAD=${!qa_var}
					[[ -n ${QA_STRICT_WX_LOAD} ]] && QA_WX_LOAD=""
					export QA_EXECSTACK="${QA_EXECSTACK} lib*/modules/*.ko"
					export QA_WX_LOAD="${QA_WX_LOAD} lib*/modules/*.ko"
					f=$(scanelf -qyRAF '%e %p' "${D}" | grep -v 'usr/lib/debug/')
					;;
			esac
			;;
		esac
		if [[ -n ${f} ]] ; then
			# One more pass to help devs track down the source
			scanelf -qyRAF '%e %p' "${PORTAGE_BUILDDIR}"/ &> "${T}"/scanelf-execstack.log
			vecho -ne '\a\n'
			eqawarn "QA Notice: The following files contain writable and executable sections"
			eqawarn " Files with such sections will not work properly (or at all!) on some"
			eqawarn " architectures/operating systems.  A bug should be filed at"
			eqawarn " http://bugs.gentoo.org/ to make sure the issue is fixed."
			eqawarn " For more information, see http://hardened.gentoo.org/gnu-stack.xml"
			eqawarn " Please include the following list of files in your report:"
			eqawarn " Note: Bugs should be filed for the respective maintainers"
			eqawarn " of the package in question and not hardened@g.o."
			eqawarn "${f}"
			vecho -ne '\a\n'
			die_msg="${die_msg} execstacks"
			sleep 1
		fi

		# Check for files built without respecting LDFLAGS
		if [[ "${LDFLAGS}" == *--hash-style=gnu* ]] && [[ "${PN}" != *-bin ]] ; then
			qa_var="QA_DT_HASH_${ARCH/-/_}"
			eval "[[ -n \${!qa_var} ]] && QA_DT_HASH=(\"\${${qa_var}[@]}\")"
			# use ED here, for the rest of the checks of scanelf's
			# output, scanelf is silent on non-existing ED
			f=$(scanelf -qyRF '%k %p' -k .hash "${ED}" | sed -e "s:\.hash ::")
			if [[ -n ${f} ]] ; then
				echo "${f}" > "${T}"/scanelf-ignored-LDFLAGS.log
				if [ "${QA_STRICT_DT_HASH-unset}" == unset ] ; then
					if [[ ${#QA_DT_HASH[@]} -gt 1 ]] ; then
						for x in "${QA_DT_HASH[@]}" ; do
							sed -e "s#^${x#/}\$##" -i "${T}"/scanelf-ignored-LDFLAGS.log
						done
					else
						local shopts=$-
						set -o noglob
						for x in ${QA_DT_HASH} ; do
							sed -e "s#^${x#/}\$##" -i "${T}"/scanelf-ignored-LDFLAGS.log
						done
						set +o noglob
						set -${shopts}
					fi
				fi
				# Filter anything under /usr/lib/debug/ in order to avoid
				# duplicate warnings for splitdebug files.
				sed -e "s#^usr/lib/debug/.*##" -e "/^\$/d" -e "s#^#/#" \
					-i "${T}"/scanelf-ignored-LDFLAGS.log
				f=$(<"${T}"/scanelf-ignored-LDFLAGS.log)
				if [[ -n ${f} ]] ; then
					vecho -ne '\a\n'
					eqawarn "${BAD}QA Notice: Files built without respecting LDFLAGS have been detected${NORMAL}"
					eqawarn " Please include the following list of files in your report:"
					eqawarn "${f}"
					vecho -ne '\a\n'
					sleep 1
				else
					rm -f "${T}"/scanelf-ignored-LDFLAGS.log
				fi
			fi
		fi

		# Save NEEDED information after removing self-contained providers
		scanelf -qyRF '%a;%p;%S;%r;%n' "${D}" | { while IFS= read l; do
			arch=${l%%;*}; l=${l#*;}
			obj="/${l%%;*}"; l=${l#*;}
			soname=${l%%;*}; l=${l#*;}
			rpath=${l%%;*}; l=${l#*;}; [ "${rpath}" = "  -  " ] && rpath=""
			needed=${l%%;*}; l=${l#*;}
			if [ -z "${rpath}" -o -n "${rpath//*ORIGIN*}" ]; then
				# object doesn't contain $ORIGIN in its runpath attribute
				echo "${obj} ${needed}"	>> "${PORTAGE_BUILDDIR}"/build-info/NEEDED
				echo "${arch:3};${obj};${soname};${rpath};${needed}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED.ELF.2
			else
				dir=${obj%/*}
				# replace $ORIGIN with the dirname of the current object for the lookup
				opath=$(echo :${rpath}: | sed -e "s#.*:\(.*\)\$ORIGIN\(.*\):.*#\1${dir}\2#")
				sneeded=$(echo ${needed} | tr , ' ')
				rneeded=""
				for lib in ${sneeded}; do
					found=0
					for path in ${opath//:/ }; do
						[ -e "${D}/${path}/${lib}" ] && found=1 && break
					done
					[ "${found}" -eq 0 ] && rneeded="${rneeded},${lib}"
				done
				rneeded=${rneeded:1}
				if [ -n "${rneeded}" ]; then
					echo "${obj} ${rneeded}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED
					echo "${arch:3};${obj};${soname};${rpath};${rneeded}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED.ELF.2
				fi
			fi
		done }

		if [[ ${insecure_rpath} -eq 1 ]] ; then
			die "Aborting due to serious QA concerns with RUNPATH/RPATH"
		elif [[ -n ${die_msg} ]] && has stricter ${FEATURES} ; then
			die "Aborting due to QA concerns: ${die_msg}"
		fi

		# Check for shared libraries lacking SONAMEs
		qa_var="QA_SONAME_${ARCH/-/_}"
		eval "[[ -n \${!qa_var} ]] && QA_SONAME=(\"\${${qa_var}[@]}\")"
		f=$(scanelf -ByF '%S %p' "${D}"{,usr/}lib*/lib*.so* | gawk '$2 == "" { print }' | sed -e "s:^[[:space:]]${D}:/:")
		if [[ -n ${f} ]] ; then
			echo "${f}" > "${T}"/scanelf-missing-SONAME.log
			if [[ "${QA_STRICT_SONAME-unset}" == unset ]] ; then
				if [[ ${#QA_SONAME[@]} -gt 1 ]] ; then
					for x in "${QA_SONAME[@]}" ; do
						sed -e "s#^/${x#/}\$##" -i "${T}"/scanelf-missing-SONAME.log
					done
				else
					local shopts=$-
					set -o noglob
					for x in ${QA_SONAME} ; do
						sed -e "s#^/${x#/}\$##" -i "${T}"/scanelf-missing-SONAME.log
					done
					set +o noglob
					set -${shopts}
				fi
			fi
			sed -e "/^\$/d" -i "${T}"/scanelf-missing-SONAME.log
			f=$(<"${T}"/scanelf-missing-SONAME.log)
			if [[ -n ${f} ]] ; then
				vecho -ne '\a\n'
				eqawarn "QA Notice: The following shared libraries lack a SONAME"
				eqawarn "${f}"
				vecho -ne '\a\n'
				sleep 1
			else
				rm -f "${T}"/scanelf-missing-SONAME.log
			fi
		fi

		# Check for shared libraries lacking NEEDED entries
		qa_var="QA_DT_NEEDED_${ARCH/-/_}"
		eval "[[ -n \${!qa_var} ]] && QA_DT_NEEDED=(\"\${${qa_var}[@]}\")"
		f=$(scanelf -ByF '%n %p' "${ED}"{,usr/}lib*.so* | gawk '$2 == "" { print }' | sed -e "s:^[[:space:]]${D}:/:")
		if [[ -n ${f} ]] ; then
			echo "${f}" > "${T}"/scanelf-missing-NEEDED.log
			if [[ "${QA_STRICT_DT_NEEDED-unset}" == unset ]] ; then
				if [[ ${#QA_DT_NEEDED[@]} -gt 1 ]] ; then
					for x in "${QA_DT_NEEDED[@]}" ; do
						sed -e "s#^/${x#/}\$##" -i "${T}"/scanelf-missing-NEEDED.log
					done
				else
					local shopts=$-
					set -o noglob
					for x in ${QA_DT_NEEDED} ; do
						sed -e "s#^/${x#/}\$##" -i "${T}"/scanelf-missing-NEEDED.log
					done
					set +o noglob
					set -${shopts}
				fi
			fi
			sed -e "/^\$/d" -i "${T}"/scanelf-missing-NEEDED.log
			f=$(<"${T}"/scanelf-missing-NEEDED.log)
			if [[ -n ${f} ]] ; then
				vecho -ne '\a\n'
				eqawarn "QA Notice: The following shared libraries lack NEEDED entries"
				eqawarn "${f}"
				vecho -ne '\a\n'
				sleep 1
			else
				rm -f "${T}"/scanelf-missing-NEEDED.log
			fi
		fi

		PORTAGE_QUIET=${tmp_quiet}
	fi
}

install_qa_check_misc() {
	local unsafe_files=$(find "${D}" -type f '(' -perm -2002 -o -perm -4002 ')')
	if [[ -n ${unsafe_files} ]] ; then
		eqawarn "QA Notice: Unsafe files detected (set*id and world writable)"
		eqawarn "${unsafe_files}"
		die "Unsafe files found in \${D}.  Portage will not install them."
	fi

	if [[ -d ${D}/${D} ]] ; then
		find "${D}/${D}" | \
		while read i ; do
			eqawarn "QA Notice: /${i##${D}/${D}} installed in \${D}/\${D}"
		done
		die "Aborting due to QA concerns: files installed in ${D}/${D}"
	fi

	# this should help to ensure that all (most?) shared libraries are executable
	# and that all libtool scripts / static libraries are not executable
	for i in "${ED}"opt/*/lib{,32,64} \
	         "${ED}"lib{,32,64}       \
	         "${ED}"usr/lib{,32,64}   \
	         "${ED}"usr/X11R6/lib{,32,64} ; do
		[[ ! -d ${i} ]] && continue

		for j in "${i}"/*.so.* "${i}"/*.so "${i}"/*.dylib "${i}"/*.dll ; do
			[[ ! -e ${j} ]] && continue
			if [[ -L ${j} ]] ; then
				linkdest=$(readlink "${j}")
				if [[ ${linkdest} == /* ]] ; then
					vecho -ne '\a\n'
					eqawarn "QA Notice: Found an absolute symlink in a library directory:"
					eqawarn "           ${j#${D}} -> ${linkdest}"
					eqawarn "           It should be a relative symlink if in the same directory"
					eqawarn "           or a linker script if it crosses the /usr boundary."
				fi
				continue
			fi
			[[ -x ${j} ]] && continue
			vecho "making executable: ${j#${D}}"
			chmod +x "${j}"
		done

		for j in "${i}"/*.a "${i}"/*.la ; do
			[[ ! -e ${j} ]] && continue
			[[ -L ${j} ]] && continue
			[[ ! -x ${j} ]] && continue
			vecho "removing executable bit: ${j#${D}}"
			chmod -x "${j}"
		done
	done

	# When installing static libraries into /usr/lib and shared libraries into 
	# /lib, we have to make sure we have a linker script in /usr/lib along side 
	# the static library, or gcc will utilize the static lib when linking :(.
	# http://bugs.gentoo.org/4411
	abort="no"
	for a in "${ED}"usr/lib*/*.a ; do
		[[ ${CHOST} == *-darwin* ]] \
			&& s=${a%.a}.dylib \
			|| s=${a%.a}.so
		if [[ ! -e ${s} ]] ; then
			s=${s%usr/*}${s##*/usr/}
			if [[ -e ${s} ]] ; then
				vecho -ne '\a\n'
				eqawarn "QA Notice: Missing gen_usr_ldscript for ${s##*/}"
	 			abort="yes"
			fi
		fi
	done
	[[ ${abort} == "yes" ]] && die "add those ldscripts"

	# Make sure people don't store libtool files or static libs in /lib
	# on AIX, "dynamic libs" have extention .a, so don't get false
	# positives
	[[ ${CHOST} == *-aix* ]] \
		&& f=$(ls "${ED}"lib*/*.la 2>/dev/null || true) \
		|| f=$(ls "${ED}"lib*/*.{a,la} 2>/dev/null)
	if [[ -n ${f} ]] ; then
		vecho -ne '\a\n'
		eqawarn "QA Notice: Excessive files found in the / partition"
		eqawarn "${f}"
		vecho -ne '\a\n'
		die "static archives (*.a) and libtool library files (*.la) do not belong in /"
	fi

	# Verify that the libtool files don't contain bogus $D entries.
	local abort=no gentoo_bug=no
	for a in "${ED}"usr/lib*/*.la ; do
		s=${a##*/}
		if grep -qs "${D}" "${a}" ; then
			vecho -ne '\a\n'
			eqawarn "QA Notice: ${s} appears to contain PORTAGE_TMPDIR paths"
			abort="yes"
		fi
	done
	[[ ${abort} == "yes" ]] && die "soiled libtool library files found"

	# Evaluate misc gcc warnings
	if [[ -n ${PORTAGE_LOG_FILE} && -r ${PORTAGE_LOG_FILE} ]] ; then
		# In debug mode, this variable definition and corresponding grep calls
		# will produce false positives if they're shown in the trace.
		local reset_debug=0
		if [[ ${-/x/} != $- ]] ; then
			set +x
			reset_debug=1
		fi
		local m msgs=(
			": warning: dereferencing type-punned pointer will break strict-aliasing rules$"
			": warning: dereferencing pointer .* does break strict-aliasing rules$"
			": warning: implicit declaration of function "
			": warning: incompatible implicit declaration of built-in function "
			": warning: is used uninitialized in this function$" # we'll ignore "may" and "might"
			": warning: comparisons like X<=Y<=Z do not have their mathematical meaning$"
			": warning: null argument where non-null required "
		)
		abort="no"
		i=0
		while [[ -n ${msgs[${i}]} ]] ; do
			m=${msgs[$((i++))]}
			# force C locale to work around slow unicode locales #160234
			f=$(LC_ALL=C grep "${m}" "${PORTAGE_LOG_FILE}")
			if [[ -n ${f} ]] ; then
				vecho -ne '\a\n'
				eqawarn "QA Notice: Package has poor programming practices which may compile"
				eqawarn "           fine but exhibit random runtime failures."
				eqawarn "${f}"
				vecho -ne '\a\n'
				abort="yes"
			fi
		done
		[[ $reset_debug = 1 ]] && set -x
		f=$(cat "${PORTAGE_LOG_FILE}" | \
			EPYTHON= "$PORTAGE_BIN_PATH"/check-implicit-pointer-usage.py)
		if [[ -n ${f} ]] ; then

			# In the future this will be a forced "die". In preparation,
			# increase the log level from "qa" to "eerror" so that people
			# are aware this is a problem that must be fixed asap.

			# just warn on 32bit hosts but bail on 64bit hosts
			case ${CHOST} in
				alpha*|hppa64*|ia64*|powerpc64*|mips64*|sparc64*|sparcv9*|x86_64*) gentoo_bug=yes ;;
			esac

			abort=yes

			if [[ $gentoo_bug = yes ]] ; then
				eerror
				eerror "QA Notice: Package has poor programming practices which may compile"
				eerror "           but will almost certainly crash on 64bit architectures."
				eerror
				eerror "${f}"
				eerror
				eerror " Please file a bug about this at http://bugs.gentoo.org/"
				eerror " with the maintaining herd of the package."
				eerror
			else
				vecho -ne '\a\n'
				eqawarn "QA Notice: Package has poor programming practices which may compile"
				eqawarn "           but will almost certainly crash on 64bit architectures."
				eqawarn "${f}"
				vecho -ne '\a\n'
			fi

		fi
		if [[ ${abort} == "yes" ]] ; then
			if [[ ${gentoo_bug} == "yes" ]] ; then
				die "install aborted due to" \
					"poor programming practices shown above"
			else
				echo "Please do not file a Gentoo bug and instead" \
				"report the above QA issues directly to the upstream" \
				"developers of this software." | fmt -w 70 | \
				while read line ; do eqawarn "${line}" ; done
				eqawarn "Homepage: ${HOMEPAGE}"
				hasq stricter ${FEATURES} && die "install aborted due to" \
					"poor programming practices shown above"
			fi
		fi
	fi

	# Compiled python objects do not belong in /usr/share (FHS violation)
	# and can be a pain when upgrading python
	f=$([ -d "${ED}"/usr/share ] && \
		find "${ED}"usr/share -name '*.py[co]' | sed "s:${D}:/:")
	if [[ -n ${f} ]] ; then
		vecho -ne '\a\n'
		eqawarn "QA Notice: Precompiled python object files do not belong in /usr/share"
		eqawarn "${f}"
		vecho -ne '\a\n'
	fi

	# Portage regenerates this on the installed system.
	rm -f "${ED}"/usr/share/info/dir{,.gz,.bz2}

	if hasq multilib-strict ${FEATURES} && \
	   [[ -x ${EPREFIX}/usr/bin/file && -x ${EPREFIX}/usr/bin/find ]] && \
	   [[ -n ${MULTILIB_STRICT_DIRS} && -n ${MULTILIB_STRICT_DENY} ]]
	then
		local abort=no firstrun=yes
		MULTILIB_STRICT_EXEMPT=$(echo ${MULTILIB_STRICT_EXEMPT} | sed -e 's:\([(|)]\):\\\1:g')
		for dir in ${MULTILIB_STRICT_DIRS} ; do
			[[ -d ${ED}/${dir} ]] || continue
			for file in $(find ${ED}/${dir} -type f | grep -v "^${ED}/${dir}/${MULTILIB_STRICT_EXEMPT}"); do
				if file ${file} | egrep -q "${MULTILIB_STRICT_DENY}" ; then
					if [[ ${firstrun} == yes ]] ; then
						echo "Files matching a file type that is not allowed:"
						firstrun=no
					fi
					abort=yes
					echo "   ${file#${ED}//}"
				fi
			done
		done
		[[ ${abort} == yes ]] && die "multilib-strict check failed!"
	fi
}

install_qa_check_prefix() {
	if [[ -d ${ED}/${D} ]] ; then
		find "${ED}/${D}" | \
		while read i ; do
			eqawarn "QA Notice: /${i##${ED}/${D}} installed in \${ED}/\${D}"
		done
		die "Aborting due to QA concerns: files installed in ${ED}/${D}"
	fi

	if [[ -d ${ED}/${EPREFIX} ]] ; then
		find "${ED}/${EPREFIX}/" | \
		while read i ; do
			eqawarn "QA Notice: ${i#${D}} double prefix"
		done
		die "Aborting due to QA concerns: double prefix files installed"
	fi

	if [[ -d ${D} ]] ; then
		INSTALLTOD=$(find ${D%/} | egrep -v "^${ED}" | sed -e "s|^${D%/}||" | awk '{if (length($0) <= length("'"${EPREFIX}"'")) { if (substr("'"${EPREFIX}"'", 1, length($0)) != $0) {print $0;} } else if (substr($0, 1, length("'"${EPREFIX}"'")) != "'"${EPREFIX}"'") {print $0;} }') 
		if [[ -n ${INSTALLTOD} ]] ; then
			eqawarn "QA Notice: the following files are outside of the prefix:"
			eqawarn "${INSTALLTOD}"
			die "Aborting due to QA concerns: there are files installed outside the prefix"
		fi
	fi

	# all further checks rely on ${ED} existing
	[[ -d ${ED} ]] || return

	# this does not really belong here, but it's closely tied to
	# the code below; many runscripts generate positives here, and we
	# know they don't work (bug #196294) so as long as that one
	# remains an issue, simply remove them as they won't work
	# anyway, avoid etc/init.d/functions.sh from being thrown away
	if [[ ( -d "${ED}"/etc/conf.d || -d "${ED}"/etc/init.d ) && ! -f "${ED}"/etc/init.d/functions.sh ]] ; then
		ewarn "removed /etc/init.d and /etc/conf.d directories until bug #196294 has been resolved"
		rm -Rf "${ED}"/etc/{conf,init}.d
	fi

	# check shebangs, bug #282539
	rm -f "${T}"/non-prefix-shebangs-errs
	local WHITELIST=" /usr/bin/env "
	# this is hell expensive, but how else?
	find "${ED}" -type f -executable -print0 \
			| xargs -0 grep -H -n -m1 "^#!" \
			| while read f ;
	do
		local fn=${f%%:*}
		local pos=${f#*:} ; pos=${pos%:*}
		local line=${f##*:}
		# shebang always appears on the first line ;)
		[[ ${pos} != 1 ]] && continue
		line=( ${line#"#!"} )
		[[ ${WHITELIST} == *" ${line[0]} "* ]] && continue
		# does the shebang start with ${EPREFIX}?
		[[ ${line[0]} == ${EPREFIX}* ]] && continue
		# can we just fix it(tm)?
		if [[ -x ${EPREFIX}${line[0]} || -x ${ED}${line[0]} ]] ; then
			eqawarn "prefixing shebang of ${fn#${D}}"
			sed -i -e '1s:^#! \?:#!'"${EPREFIX}"':' "${fn}"
			continue
		fi
		# all else is an error if the found script is in $PATH
		local fp=${fn#${D}} ; fp=${fp%/*}
		if [[ ":${PATH}:" == *":${fp}:"* ]] || hasq stricter ${FEATURES} ;
		then
			echo "${fn#${D}}:${line[0]}" \
				>> "${T}"/non-prefix-shebangs-errs
		else
			eqawarn "invalid shebang in ${fn#${D}}: ${line[0]}"
		fi
	done
	if [[ -e "${T}"/non-prefix-shebangs-errs ]] ; then
		eqawarn "QA Notice: the following files use invalid (possible non-prefixed) shebangs:"
		eqawarn "$(<"${T}"/non-prefix-shebangs-errs)"
		die "Aborting due to QA concerns: invalid shebangs found"
		rm -f "${T}"/non-prefix-shebangs-errs
	fi
}

install_qa_check_macho() {
	if ! hasq binchecks ${RESTRICT} ; then
		# on Darwin, dynamic libraries are called .dylibs instead of
		# .sos.  In addition the version component is before the
		# extension, not after it.  Check for this, and *only* warn
		# about it.  Some packages do ship .so files on Darwin and make
		# it work (ugly!).
		rm -f "${T}/mach-o.check"
		find ${ED%/} -name "*.so" -or -name "*.so.*" | \
		while read i ; do
			[[ $(file $i) == *"Mach-O"* ]] && \
				echo "${i#${D}}" >> "${T}/mach-o.check"
		done
		if [[ -f ${T}/mach-o.check ]] ; then
			f=$(< "${T}/mach-o.check")
			vecho -ne '\a\n'
			eqawarn "QA Notice: Found .so dynamic libraries on Darwin:"
			eqawarn "    ${f//$'\n'/\n    }"
		fi
		rm -f "${T}/mach-o.check"

		# The naming for dynamic libraries is different on Darwin; the
		# version component is before the extention, instead of after
		# it, as with .sos.  Again, make this a warning only.
		rm -f "${T}/mach-o.check"
		find ${ED%/} -name "*.dylib.*" | \
		while read i ; do
			echo "${i#${D}}" >> "${T}/mach-o.check"
		done
		if [[ -f "${T}/mach-o.check" ]] ; then
			f=$(< "${T}/mach-o.check")
			vecho -ne '\a\n'
			eqawarn "QA Notice: Found wrongly named dynamic libraries on Darwin:"
			eqawarn "    ${f// /\n    }"
		fi
		rm -f "${T}/mach-o.check"
	fi

	# While we generate the NEEDED files, check that we don't get kernel
	# traps at runtime because of broken install_names on Darwin.
	rm -f "${T}"/.install_name_check_failed
	scanmacho -qyRF '%a;%p;%S;%n' "${D}" | { while IFS= read l ; do
		arch=${l%%;*}; l=${l#*;}
		obj="/${l%%;*}"; l=${l#*;}
		install_name=${l%%;*}; l=${l#*;}
		needed=${l%%;*}; l=${l#*;}

		# See if the self-reference install_name points to an existing
		# and to be installed file.  This usually is a symlink for the
		# major version.
		if [[ ! -e ${D}${install_name} ]] ; then
			eqawarn "QA Notice: invalid self-reference install_name ${install_name} in ${obj}"
			# remember we are in an implicit subshell, that's
			# why we touch a file here ... ideally we should be
			# able to die correctly/nicely here
			touch "${T}"/.install_name_check_failed
		fi

		# this is ugly, paths with spaces won't work
		reevaluate=0
		for lib in $(echo ${needed} | tr , ' '); do
			if [[ ! -e ${lib} && ! -e ${D}${lib} && ${lib} != "@executable_path/"* && *${lib} != "@loader_path/"* ]] ; then
				# try to "repair" this if possible, happens because of
				# gen_usr_ldscript tactics
				s=${lib%usr/*}${lib##*/usr/}
				if [[ -e ${D}${s} ]] ; then
					ewarn "correcting install_name from ${lib} to ${s} in ${obj}"
					install_name_tool -change \
						"${lib}" "${s}" "${D}${obj}"
					reevaluate=1
				else
					eqawarn "QA Notice: invalid reference to ${lib} in ${obj}"
					# remember we are in an implicit subshell, that's
					# why we touch a file here ... ideally we should be
					# able to die correctly/nicely here
					touch "${T}"/.install_name_check_failed
				fi
			fi
		done
		if [[ ${reevaluate} == 1 ]]; then
			# install_name(s) have been changed, refresh data so we
			# store the correct meta data
			l=$(scanmacho -qyF '%a;%p;%S;%n' ${D}${obj})
			arch=${l%%;*}; l=${l#*;}
			obj="/${l%%;*}"; l=${l#*;}
			install_name=${l%%;*}; l=${l#*;}
			needed=${l%%;*}; l=${l#*;}
		fi

		# backwards compatability
		echo "${obj} ${needed}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED
		# what we use
		echo "${arch};${obj};${install_name};${needed}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED.MACHO.3
	done }
	if [[ -f ${T}/.install_name_check_failed ]] ; then
		# secret switch "allow_broken_install_names" to get
		# around this and install broken crap (not a good idea)
		hasq allow_broken_install_names ${FEATURES} || \
			die "invalid install_name found, your application or library will crash at runtime"
	fi
}

install_qa_check_pecoff() {
	local _pfx_scan="readpecoff ${CHOST}"

	# this one uses readpecoff, which supports multiple prefix platforms!
	# this is absolutely _not_ optimized for speed, and there may be plenty
	# of possibilities by introducing one or the other cache!
	if ! hasq binchecks ${RESTRICT}; then
		# copied and adapted from the above scanelf code.
		local qa_var insecure_rpath=0 tmp_quiet=${PORTAGE_QUIET}
		local f x

		# display warnings when using stricter because we die afterwards
		if has stricter ${FEATURES} ; then
			unset PORTAGE_QUIET
		fi

		local _exec_find_opt="-executable"
		[[ ${CHOST} == *-winnt* ]] && _exec_find_opt='-name *.dll -o -name *.exe'

		# Make sure we disallow insecure RUNPATH/RPATH's
		# Don't want paths that point to the tree where the package was built
		# (older, broken libtools would do this).  Also check for null paths
		# because the loader will search $PWD when it finds null paths.

		f=$(
			find "${ED}" -type f '(' ${_exec_find_opt} ')' -print0 | xargs -0 ${_pfx_scan} | \
			while IFS=";" read arch obj soname rpath needed ; do \
			echo "${rpath}" | grep -E "(${PORTAGE_BUILDDIR}|: |::|^:|^ )" > /dev/null 2>&1 \
				&& echo "${obj}"; done;
		)
		# Reject set*id binaries with $ORIGIN in RPATH #260331
		x=$(
			find "${ED}" -type f '(' -perm -u+s -o -perm -g+s ')' -print0 | \
			xargs -0 ${_pfx_scan} | while IFS=";" read arch obj soname rpath needed; do \
			echo "${rpath}" | grep '$ORIGIN' > /dev/null 2>&1 && echo "${obj}"; done;
		)
		if [[ -n ${f}${x} ]] ; then
			vecho -ne '\a\n'
			eqawarn "QA Notice: The following files contain insecure RUNPATH's"
			eqawarn " Please file a bug about this at http://bugs.gentoo.org/"
			eqawarn " with the maintaining herd of the package."
			eqawarn "${f}${f:+${x:+\n}}${x}"
			vecho -ne '\a\n'
			if [[ -n ${x} ]] || has stricter ${FEATURES} ; then
				insecure_rpath=1
			else
				eqawarn "cannot automatically fix runpaths on interix platforms!"
			fi
		fi

		rm -f "${PORTAGE_BUILDDIR}"/build-info/NEEDED
		rm -f "${PORTAGE_BUILDDIR}"/build-info/NEEDED.PECOFF.1

		# Save NEEDED information after removing self-contained providers
		find "${ED}" -type f '(' ${_exec_find_opt} ')' -print0 | xargs -0 ${_pfx_scan} | { while IFS=';' read arch obj soname rpath needed; do
			# need to strip image dir from object name.
			obj="/${obj#${D}}"
			if [ -z "${rpath}" -o -n "${rpath//*ORIGIN*}" ]; then
				# object doesn't contain $ORIGIN in its runpath attribute
				echo "${obj} ${needed}"	>> "${PORTAGE_BUILDDIR}"/build-info/NEEDED
				echo "${arch};${obj};${soname};${rpath};${needed}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED.PECOFF.1
			else
				dir=${obj%/*}
				# replace $ORIGIN with the dirname of the current object for the lookup
				opath=$(echo :${rpath}: | sed -e "s#.*:\(.*\)\$ORIGIN\(.*\):.*#\1${dir}\2#")
				sneeded=$(echo ${needed} | tr , ' ')
				rneeded=""
				for lib in ${sneeded}; do
					found=0
					for path in ${opath//:/ }; do
						[ -e "${ED}/${path}/${lib}" ] && found=1 && break
					done
					[ "${found}" -eq 0 ] && rneeded="${rneeded},${lib}"
				done
				rneeded=${rneeded:1}
				if [ -n "${rneeded}" ]; then
					echo "${obj} ${rneeded}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED
					echo "${arch};${obj};${soname};${rpath};${rneeded}" >> "${PORTAGE_BUILDDIR}"/build-info/NEEDED.PECOFF.1
				fi
			fi
		done }
		
		if [[ ${insecure_rpath} -eq 1 ]] ; then
			die "Aborting due to serious QA concerns with RUNPATH/RPATH"
		elif [[ -n ${die_msg} ]] && has stricter ${FEATURES} ; then
			die "Aborting due to QA concerns: ${die_msg}"
		fi

		local _so_ext='.so*'

		case "${CHOST}" in
			*-winnt*) _so_ext=".dll" ;; # no "*" intentionally!
		esac

		# Run some sanity checks on shared libraries
		for d in "${ED}"lib* "${ED}"usr/lib* ; do
			[[ -d "${d}" ]] || continue
			f=$(find "${d}" -name "lib*${_so_ext}" -print0 | \
				xargs -0 ${_pfx_scan} | while IFS=";" read arch obj soname rpath needed; \
				do [[ -z "${soname}" ]] && echo "${obj}"; done)
			if [[ -n ${f} ]] ; then
				vecho -ne '\a\n'
				eqawarn "QA Notice: The following shared libraries lack a SONAME"
				eqawarn "${f}"
				vecho -ne '\a\n'
				sleep 1
			fi

			f=$(find "${d}" -name "lib*${_so_ext}" -print0 | \
				xargs -0 ${_pfx_scan} | while IFS=";" read arch obj soname rpath needed; \
				do [[ -z "${needed}" ]] && echo "${obj}"; done)
			if [[ -n ${f} ]] ; then
				vecho -ne '\a\n'
				eqawarn "QA Notice: The following shared libraries lack NEEDED entries"
				eqawarn "${f}"
				vecho -ne '\a\n'
				sleep 1
			fi
		done

		PORTAGE_QUIET=${tmp_quiet}
	fi
}

install_qa_check_xcoff() {
	if ! hasq binchecks ${RESTRICT}; then
		local tmp_quiet=${PORTAGE_QUIET}
		local queryline deplib
		local insecure_rpath_list= undefined_symbols_list=

		# display warnings when using stricter because we die afterwards
		if has stricter ${FEATURES} ; then
			unset PORTAGE_QUIET
		fi

		rm -f "${PORTAGE_BUILDDIR}"/build-info/NEEDED.XCOFF.1

		local neededfd
		for neededfd in {3..1024} none; do ( : <&${neededfd} ) 2>/dev/null || break; done
		[[ ${neededfd} != none ]] || die "cannot find free file descriptor handle"

		eval "exec ${neededfd}>\"${PORTAGE_BUILDDIR}\"/build-info/NEEDED.XCOFF.1" || die "cannot open ${PORTAGE_BUILDDIR}/build-info/NEEDED.XCOFF.1"

		find "${ED}" -not -type d -exec \
			"${EPREFIX}/usr/bin/aixdll-query" '{}' FILE MEMBER FLAGS FORMAT RUNPATH DEPLIBS ';' \
			> "${T}"/needed 2>/dev/null

		# Symlinking archive libraries is not a good idea on aix,
		# as there is nothing like "soname" on pure filesystem level.
		# So we create a copy instead of the symlink.
		local prev_FILE=
		while read queryline
		do
			local FILE= MEMBER= FLAGS= FORMAT= RUNPATH= DEPLIBS=
			eval ${queryline}

			if [[ ${prev_FILE} != ${FILE} ]]; then
				prev_FILE=${FILE}
				if [[ -n ${MEMBER} || " ${FLAGS} " == *" SHROBJ "* ]] && [[ -h ${FILE} ]]; then
					local target=$(readlink "${FILE}")
					if [[ ${target} == /* ]]; then
						target=${D}${target}
					else
						target=${FILE%/*}/${target}
					fi
					rm -f "${FILE}" || die "cannot prune ${FILE#${ED}}"
					cp -f "${target}" "${FILE}" || die "cannot copy ${target#${ED}} to ${FILE#${ED}}"
				fi
			fi
		done <"${T}"/needed

		prev_FILE=
		while read queryline
		do
			local FILE= MEMBER= FLAGS= FORMAT= RUNPATH= DEPLIBS=
			eval ${queryline}

			if [[ -n ${MEMBER} && ${prev_FILE} != ${FILE} ]]; then
				# Save NEEDED information for the archive library stub
				echo "${FORMAT##* }${FORMAT%%-*};${FILE#${D%/}};${FILE##*/};;" >&${neededfd}
			fi
			prev_FILE=${FILE}

			# Make sure we disallow insecure RUNPATH's
			# Don't want paths that point to the tree where the package was built
			# (older, broken libtools would do this).  Also check for null paths
			# because the loader will search $PWD when it finds null paths.
			# And we really want absolute paths only.
			if [[ " ${FLAGS} " == *" SHROBJ "* && -n $(echo ":${RUNPATH}:" | grep -E "(${PORTAGE_BUILDDIR}|::|:[^/])") ]]; then
				insecure_rpath_list="${insecure_rpath_list}\n${FILE}${MEMBER:+[${MEMBER}]}"
			fi

			# Although we do have runtime linking, we don't want undefined symbols.
			# AIX does indicate this by needing either '.' or '..'
			local needed=${FILE##*/}
			for deplib in ${DEPLIBS}; do
				eval deplib=${deplib}
				if [[ ${deplib} == '.' || ${deplib} == '..' ]]; then
					undefined_symbols_list="${undefined_symbols_list}\n${FILE}"
				else
					needed="${needed},${deplib}"
				fi
			done

			FILE=${FILE#${D%/}}

			[[ -n ${MEMBER} ]] && MEMBER="[${MEMBER}]"
			# Save NEEDED information
			echo "${FORMAT##* }${FORMAT%%-*};${FILE}${MEMBER};${FILE##*/}${MEMBER};${RUNPATH};${needed}" >&${neededfd}
		done <"${T}"/needed

		eval "exec ${neededfd}>&-" || die "cannot close handle to ${PORTAGE_BUILDDIR}/build-info/NEEDED.XCOFF.1"

		if [[ -n ${undefined_symbols_list} ]]; then
			vecho -ne '\a\n'
			eqawarn "QA Notice: The following files contain undefined symbols."
			eqawarn " Please file a bug about this at http://bugs.gentoo.org/"
			eqawarn " with 'prefix' as the maintaining herd of the package."
			eqawarn "${undefined_symbols_list}"
			vecho -ne '\a\n'
		fi

		if [[ -n ${insecure_rpath_list} ]] ; then
			vecho -ne '\a\n'
			eqawarn "QA Notice: The following files contain insecure RUNPATH's"
			eqawarn " Please file a bug about this at http://bugs.gentoo.org/"
			eqawarn " with 'prefix' as the maintaining herd of the package."
			eqawarn "${insecure_rpath_list}"
			vecho -ne '\a\n'
			if has stricter ${FEATURES} ; then
				insecure_rpath=1
			fi
		fi

		if [[ ${insecure_rpath} -eq 1 ]] ; then
			die "Aborting due to serious QA concerns with RUNPATH/RPATH"
		elif [[ -n ${die_msg} ]] && has stricter ${FEATURES} ; then
			die "Aborting due to QA concerns: ${die_msg}"
		fi

		PORTAGE_QUIET=${tmp_quiet}
	fi
}


install_mask() {
	local root="$1"
	shift
	local install_mask="$*"

	# we don't want globbing for initial expansion, but afterwards, we do
	local shopts=$-
	set -o noglob
	for no_inst in ${install_mask}; do
		set +o noglob
		quiet_mode || einfo "Removing ${no_inst}"
		# normal stuff
		rm -Rf "${root}"/${no_inst} >&/dev/null

		# we also need to handle globs (*.a, *.h, etc)
		find "${root}" \( -path "${no_inst}" -or -name "${no_inst}" \) \
			-exec rm -fR {} \; >/dev/null 2>&1
	done
	# set everything back the way we found it
	set +o noglob
	set -${shopts}
}

preinst_bsdflags() {
	hasq chflags $FEATURES || return
	# Save all the file flags for restoration after installation.
	mtree -c -p "${D}" -k flags > "${T}/bsdflags.mtree"
	# Remove all the file flags so that the merge phase can do anything
	# necessary.
	chflags -R noschg,nouchg,nosappnd,nouappnd "${D}"
	chflags -R nosunlnk,nouunlnk "${D}" 2>/dev/null
}

postinst_bsdflags() {
	hasq chflags $FEATURES || return
	# Restore all the file flags that were saved before installation.
	mtree -e -p "${ROOT}" -U -k flags < "${T}/bsdflags.mtree" &> /dev/null
}

preinst_aix() {
	if [[ ${CHOST} != *-aix* ]] || hasq binchecks ${RESTRICT}; then
		return 0
	fi
	local ar strip
	if type ${CHOST}-ar >/dev/null 2>&1 && type ${CHOST}-strip >/dev/null 2>&1; then
		ar=${CHOST}-ar
		strip=${CHOST}-strip
	elif [[ ${CBUILD} == "${CHOST}" ]] && type ar >/dev/null 2>&1 && type strip >/dev/null 2>&1; then
		ar=ar
		strip=strip
	elif [[ -x /usr/ccs/bin/ar && -x /usr/ccs/bin/strip ]]; then
		ar=/usr/ccs/bin/ar
		strip=/usr/ccs/bin/strip
	else
		die "cannot find where to use 'ar' and 'strip' from"
	fi

	local archive prev_archive= archives=()
	while read archive; do
		archive=${archive#*;}
		archive=${archive%%;*}
		if [[ ${archive} == *'['*']' ]]; then
			archive=${archive%[*}
			[[ ${prev_archive} == ${archive} ]] && continue
			prev_archive=${archive}
			archives[${#archives[@]}]=${archive#${EPREFIX}/}
		fi
	done < "${PORTAGE_BUILDDIR}"/build-info/NEEDED.XCOFF.1
	unset prev_archive

	local libmetadir members preservemembers member contentmember chmod400files=() prunedirs=()
	for archive in "${archives[@]}"; do
		libmetadir=${ED}${archive%/*}/.${archive##*/}
		[[ ! -e ${libmetadir} ]] || rm -rf "${libmetadir}" || die "cannot prune ${libmetadir}"
		mkdir "${libmetadir}" || die "cannot create ${libmetadir}"
		pushd "${libmetadir}" >/dev/null || die "cannot cd to ${libmetadir}"
		${ar} -X32_64 -x "${ED}${archive}" || die "cannot unpack ${archive}"
		members=" $(echo *) "
		preservemembers=
		if [[ -e ${EROOT}${archive} ]]; then
			for member in $(${ar} -X32_64 -t "${EROOT}${archive}"); do
				[[ ${members} == *" ${member} "* ]] && continue
				preservemembers="${preservemembers} ${member}"
			done
			if [[ -n ${preservemembers} ]]; then
				einfo "preserving (on spec)${preservemembers}"
				${ar} -X32_64 -x "${EROOT}${archive}" ${preservemembers} || die "cannot extract ${preservemembers} from ${EROOT}${archive}"
				chmod u+w ${preservemembers} || die "cannot chmod${preservedmembers}"
				${strip} -X32_64 -e ${preservemembers} || die "cannot strip${preservemembers}"
				${ar} -X32_64 -q "${ED}${archive}" ${preservemembers} || die "cannot update ${archive}"
				eend $?
			fi
		fi
		for member in ${members}; do
			contentmember="${archive%/*}/.${archive##*/}[${member}]"
			# portage does os.lstat() on merged files every now
			# and then, so keep stamp-files for archive members
			# around to get the preserve-libs feature working.
			{	echo "Please leave this file alone, it is an important helper"
				echo "for portage to implement the 'preserve-libs' feature on AIX." 
			} > "${ED}${contentmember}" || die "cannot create ${contentmember}"
			chmod400files[${#chmod400files[@]}]=${ED}${contentmember}
		done
		popd >/dev/null || die "cannot leave ${libmetadir}"
		prunedirs[${#prunedirs[@]}]=${libmetadir}
	done
	[[ ${#chmod400files[@]} == 0 ]] ||
	chmod 0400 "${chmod400files[@]}" || die "cannot chmod ${chmod400files[@]}"
	[[ ${#prunedirs[@]} == 0 ]] ||
	rm -rf "${prunedirs[@]}" || die "cannot prune ${prunedirs[@]}"
	return 0
}

postinst_aix() {
	if [[ ${CHOST} != *-aix* ]] || hasq binchecks ${RESTRICT}; then
		return 0
	fi
	local MY_PR=${PR%r0}
	local ar strip
	if type ${CHOST}-ar >/dev/null 2>&1 && type ${CHOST}-strip >/dev/null 2>&1; then
		ar=${CHOST}-ar
		strip=${CHOST}-strip
	elif [[ ${CBUILD} == "${CHOST}" ]] && type ar >/dev/null 2>&1 && type strip >/dev/null 2>&1; then
		ar=ar
		strip=strip
	elif [[ -x /usr/ccs/bin/ar && -x /usr/ccs/bin/strip ]]; then
		ar=/usr/ccs/bin/ar
		strip=/usr/ccs/bin/strip
	else
		die "cannot find where to use 'ar' and 'strip' from"
	fi

	local member contentmember activecontentmembers= prev_archive= archive activearchives=
	while read member; do
		member=${member#*;} # drop "^type;"
		member=${member%%;*} # drop ";soname;runpath;needed$"
		[[ ${member##*/} == *'['*']' ]] || continue
		contentmember=${member%/*}/.${member##*/}
		activecontentmembers="${activecontentmembers}:(${contentmember}):"
		archive=${member%[*}
		[[ ${prev_archive} != ${archive} ]] || continue
		prev_archive=${archive}
		activearchives="${activearchives}:(${archive}):"
	done < "${PORTAGE_BUILDDIR}"/build-info/NEEDED.XCOFF.1

	local type allcontentmembers= all_archives=()
	prev_archive=
	while read type contentmember; do
		contentmember=${contentmember% *} # drop " timestamp$"
		contentmember=${contentmember% *} # drop " hash$"
		[[ ${contentmember##*/} == *'['*']' ]] || continue
		allcontentmembers="${allcontentmembers}:(${contentmember}):"
		member=${contentmember%/.*}/${contentmember##*/.}
		archive=${member%[*}
		[[ ${prev_archive} != ${archive} ]] || continue
		prev_archive=${archive}
		all_archives[${#all_archives[@]}]=${archive}
	done < "${EPREFIX}/var/db/pkg/${CATEGORY}/${P}${MY_PR:+-}${MY_PR}/CONTENTS"

	local delmembers oldmembers libmetadir prunemembers=() prunedirs=()
	for archive in "${all_archives[@]}"; do
		[[ -r ${ROOT}${archive} && -w ${ROOT}${archive} ]] ||
		chmod a+r,u+w "${ROOT}${archive}" || die "cannot chmod ${archive}"
		delmembers= oldmembers=
		for member in $(${ar} -X32_64 -t "${ROOT}${archive}"); do
			contentmember="${archive%/*}/.${archive##*/}[${member}]"
			if [[ ${allcontentmembers} != *":(${contentmember}):"* ]]; then
				# not existent any more, just drop it
				delmembers="${delmembers} ${member}"
				prunemembers[${#prunemembers[@]}]=${ROOT}${contentmember}
			elif [[ ${activecontentmembers} != *":(${contentmember}):"* ]]; then
				oldmembers="${oldmembers} ${member}"
			fi
		done
		if [[ -n ${delmembers} ]]; then
			einfo "dropping${delmembers}"
			${ar} -X32_64 -z -o -d "${ROOT}${archive}" ${delmembers} || die "cannot remove${delmembers} from ${archive}"
			eend $?
		fi
		if [[ -n ${oldmembers} && ${activearchives} != *":(${archive}):"* ]]; then
			einfo "preserving (extra)${oldmembers}"
			libmetadir=${ROOT}${archive%/*}/.${archive##*/}
			[[ ! -e ${libmetadir} ]] || rm -rf "${libmetadir}" || die "cannot prune ${libmetadir}"
			mkdir "${libmetadir}" || die "cannot create ${libmetadir}"
			pushd "${libmetadir}" >/dev/null || die "cannot cd to ${libmetadir}"
			${ar} -X32_64 -x "${ROOT}${archive}" ${oldmembers} || die "cannot unpack ${archive}"
			${strip} -e ${oldmembers} || die "cannot strip ${oldmembers}"
			${ar} -X32_64 -z -o -r "${ROOT}${archive}" ${oldmembers} || die "cannot update${oldmembers} in ${archive}"
			popd > /dev/null || die "cannot leave ${libmetadir}"
			prunedirs[${#prunedirs[@]}]=${libmetadir}
			eend $?
		fi
	done
	[[ ${#prunedirs[@]} == 0 ]] ||
	rm -rf "${prunedirs[@]}" || die "cannot prune ${prunedirs[@]}"
	[[ ${#prunemembers[@]} == 0 ]] ||
	rm -f "${prunemembers[@]}" || die "cannot prune ${contentmenbers[@]}"
	return 0
}

preinst_mask() {
	if [ -z "${D}" ]; then
		 eerror "${FUNCNAME}: D is unset"
		 return 1
	fi

	# Make sure $PWD is not ${D} so that we don't leave gmon.out files
	# in there in case any tools were built with -pg in CFLAGS.
	cd "${T}"

	# remove man pages, info pages, docs if requested
	for f in man info doc; do
		if hasq no${f} $FEATURES; then
			INSTALL_MASK="${INSTALL_MASK} ${EPREFIX}/usr/share/${f}"
		fi
	done

	install_mask "${D}" "${INSTALL_MASK}"

	# remove share dir if unnessesary
	if hasq nodoc $FEATURES -o hasq noman $FEATURES -o hasq noinfo $FEATURES; then
		rmdir "${D}usr/share" &> /dev/null
	fi
}

preinst_sfperms() {
	if [ -z "${D}" ]; then
		 eerror "${FUNCNAME}: D is unset"
		 return 1
	fi
	# Smart FileSystem Permissions
	if hasq sfperms $FEATURES; then
		local i
		find "${D}" -type f -perm -4000 -print0 | \
		while read -d $'\0' i ; do
			if [ -n "$(find "$i" -perm -2000)" ] ; then
				ebegin ">>> SetUID and SetGID: [chmod o-r] /${i#${D}}"
				chmod o-r "$i"
				eend $?
			else
				ebegin ">>> SetUID: [chmod go-r] /${i#${D}}"
				chmod go-r "$i"
				eend $?
			fi
		done
		find "${D}" -type f -perm -2000 -print0 | \
		while read -d $'\0' i ; do
			if [ -n "$(find "$i" -perm -4000)" ] ; then
				# This case is already handled
				# by the SetUID check above.
				true
			else
				ebegin ">>> SetGID: [chmod o-r] /${i#${D}}"
				chmod o-r "$i"
				eend $?
			fi
		done
	fi
}

preinst_suid_scan() {
	if [ -z "${D}" ]; then
		 eerror "${FUNCNAME}: D is unset"
		 return 1
	fi
	# total suid control.
	if hasq suidctl $FEATURES; then
		local sfconf
		sfconf=${PORTAGE_CONFIGROOT}${EPREFIX#/}/etc/portage/suidctl.conf
		# sandbox prevents us from writing directly
		# to files outside of the sandbox, but this
		# can easly be bypassed using the addwrite() function
		addwrite "${sfconf}"
		vecho ">>> Performing suid scan in ${D}"
		for i in $(find "${D}" -type f \( -perm -4000 -o -perm -2000 \) ); do
			if [ -s "${sfconf}" ]; then
				install_path=/${i#${D}}
				if grep -q "^${install_path}\$" "${sfconf}" ; then
					vecho "- ${install_path} is an approved suid file"
				else
					vecho ">>> Removing sbit on non registered ${install_path}"
					for x in 5 4 3 2 1 0; do echo -ne "\a"; sleep 0.25 ; done
					vecho -ne "\a"
					ls_ret=$(ls -ldh "${i}")
					chmod ugo-s "${i}"
					grep "^#${install_path}$" "${sfconf}" > /dev/null || {
						vecho ">>> Appending commented out entry to ${sfconf} for ${PF}"
						echo "## ${ls_ret%${D}*}${install_path}" >> "${sfconf}"
						echo "#${install_path}" >> "${sfconf}"
						# no delwrite() eh?
						# delwrite ${sconf}
					}
				fi
			else
				vecho "suidctl feature set but you are lacking a ${sfconf}"
			fi
		done
	fi
}

preinst_selinux_labels() {
	if [ -z "${D}" ]; then
		 eerror "${FUNCNAME}: D is unset"
		 return 1
	fi
	if hasq selinux ${FEATURES}; then
		# SELinux file labeling (needs to always be last in dyn_preinst)
		# only attempt to label if setfiles is executable
		# and 'context' is available on selinuxfs.
		if [ -f "${EPREFIX}"/selinux/context -a -x "${EPREFIX}"/usr/sbin/setfiles -a -x "${EPREFIX}"/usr/sbin/selinuxconfig ]; then
			vecho ">>> Setting SELinux security labels"
			(
				eval "$("${EPREFIX}"/usr/sbin/selinuxconfig)" || \
					die "Failed to determine SELinux policy paths.";
	
				addwrite /selinux/context;
	
				"${EPREFIX}"/usr/sbin/setfiles "${file_contexts_path}" -r "${D}" "${D}"
			) || die "Failed to set SELinux security labels."
		else
			# nonfatal, since merging can happen outside a SE kernel
			# like during a recovery situation
			vecho "!!! Unable to set SELinux security labels"
		fi
	fi
}

dyn_package() {
	# Make sure $PWD is not ${D} so that we don't leave gmon.out files
	# in there in case any tools were built with -pg in CFLAGS.
	cd "${T}"
	install_mask "${PORTAGE_BUILDDIR}/image" "${PKG_INSTALL_MASK}"
	local tar_options=""
	[[ $PORTAGE_VERBOSE = 1 ]] && tar_options+=" -v"
	# Sandbox is disabled in case the user wants to use a symlink
	# for $PKGDIR and/or $PKGDIR/All.
	export SANDBOX_ON="0"
	[ -z "${PORTAGE_BINPKG_TMPFILE}" ] && \
		PORTAGE_BINPKG_TMPFILE="${PKGDIR}/${CATEGORY}/${PF}.tbz2"
	mkdir -p "${PORTAGE_BINPKG_TMPFILE%/*}" || die "mkdir failed"
	tar $tar_options -cf - $PORTAGE_BINPKG_TAR_OPTS -C "${D}" . | \
		bzip2 -cf > "$PORTAGE_BINPKG_TMPFILE"
	assert "failed to pack binary package: '$PORTAGE_BINPKG_TMPFILE'"
	EPYTHON= PYTHONPATH=${PORTAGE_PYM_PATH}${PYTHONPATH:+:}${PYTHONPATH} \
		"$PORTAGE_BIN_PATH"/xpak-helper.py recompose \
		"$PORTAGE_BINPKG_TMPFILE" "$PORTAGE_BUILDDIR/build-info"
	if [ $? -ne 0 ]; then
		rm -f "${PORTAGE_BINPKG_TMPFILE}"
		die "Failed to append metadata to the tbz2 file"
	fi
	local md5_hash=""
	if type md5sum &>/dev/null ; then
		md5_hash=$(md5sum "${PORTAGE_BINPKG_TMPFILE}")
		md5_hash=${md5_hash%% *}
	elif type md5 &>/dev/null ; then
		md5_hash=$(md5 "${PORTAGE_BINPKG_TMPFILE}")
		md5_hash=${md5_hash##* }
	fi
	[ -n "${md5_hash}" ] && \
		echo ${md5_hash} > "${PORTAGE_BUILDDIR}"/build-info/BINPKGMD5
	vecho ">>> Done."
	cd "${PORTAGE_BUILDDIR}"
	touch .packaged || die "Failed to 'touch .packaged' in ${PORTAGE_BUILDDIR}"
}

dyn_spec() {
	local sources_dir=/usr/src/rpm/SOURCES
	mkdir -p "${sources_dir}"
	tar czf "${sources_dir}/${PF}.tar.gz" \
		"${EBUILD}" "${FILESDIR}" || \
		die "Failed to create base rpm tarball."

	cat <<__END1__ > ${PF}.spec
Summary: ${DESCRIPTION}
Name: ${PN}
Version: ${PV}
Release: ${PR}
Copyright: GPL
Group: portage/${CATEGORY}
Source: ${PF}.tar.gz
Buildroot: ${D}
%description
${DESCRIPTION}

${HOMEPAGE}

%prep
%setup -c

%build

%install

%clean

%files
/
__END1__

}

dyn_rpm() {
	cd "${T}" || die "cd failed"
	local machine_name=$(uname -m)
	local dest_dir=/usr/src/rpm/RPMS/${machine_name}
	addwrite /usr/src/rpm
	addwrite "${RPMDIR}"
	dyn_spec
	rpmbuild -bb --clean --rmsource "${PF}.spec" || die "Failed to integrate rpm spec file"
	install -D "${dest_dir}/${PN}-${PV}-${PR}.${machine_name}.rpm" \
		"${RPMDIR}/${CATEGORY}/${PN}-${PV}-${PR}.rpm" || \
		die "Failed to move rpm"
}

if [ -n "${MISC_FUNCTIONS_ARGS}" ]; then
	source_all_bashrcs
	[ "$PORTAGE_DEBUG" == "1" ] && set -x
	for x in ${MISC_FUNCTIONS_ARGS}; do
		${x}
	done
fi

[ -n "${EBUILD_EXIT_STATUS_FILE}" ] && \
	touch "${EBUILD_EXIT_STATUS_FILE}" &>/dev/null

:
