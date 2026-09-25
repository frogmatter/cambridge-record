/**
 * Single meeting — video + transcript.
 * Source: GET /wp-json/wp/v2/meeting/{id}?_fields=id,meta
 *         (segments_json, votes_json, agenda_json)
 *
 * Talking to the Cablecast player (cross-origin iframe, Video.js inside):
 *   ?seek=N in the embed URL                  start at N seconds and play
 *   → postMessage {type:'player-cue', value:N} jump to N and play (no reload)
 *   ← {message:'ready'}                       player loaded
 *   ← {message:'timeupdate', value:seconds}   several times a second while playing
 *   ← {message:'playing', value:bool}         play / pause
 * (Found by reading Cablecast's VideoJs-*.js bundle, Sept 2026. The embed
 * ignores &t= — that's why the pipeline's old deep links started at 0:00.)
 *
 * URLs:  /meeting/slug/#t=3725        open at 1:02:05
 *        /meeting/slug/?q=budget#t=…  also highlight "budget" (from search)
 */
( function () {
    'use strict';

    const { api, el, parseJson, fmtTime, highlight, debounce, status, voteLabel, tallyText } = window.CR;

    const root = document.getElementById( 'meeting' );
    if ( ! root ) return;

    const postId       = root.dataset.id;
    const embedUrl     = root.dataset.embed;
    const player       = document.getElementById( 'player' );
    const mediaEl      = document.querySelector( '.meeting-media' );
    const toolsEl      = document.querySelector( '.transcript-tools' );
    const nowEl        = document.getElementById( 'player-now' );
    const followBtn    = document.getElementById( 'follow-video' );
    const copyBtn      = document.getElementById( 'copy-moment' );
    const watchLink    = document.getElementById( 'watch-external' );
    const transcriptEl = document.getElementById( 'transcript' );
    const findEl       = document.getElementById( 'find' );
    const findCountEl  = document.getElementById( 'find-count' );
    const prevBtn      = document.getElementById( 'find-prev' );
    const nextBtn      = document.getElementById( 'find-next' );

    const playerOrigin = embedUrl ? new URL( embedUrl, window.location.href ).origin : null;

    let cues = [];          // [{ start, text, isVote, span }] sorted by start
    let activeCue = null;
    let currentTime = null; // whole seconds
    let playerReady = false;
    let isPlaying = false;
    let following = true;   // keep the spoken line in view while the video plays
    let matches = [];       // <mark> elements for the find box
    let matchIndex = -1;
    let markedCues = [];    // cues whose text currently contains <mark>s


    // ── Player ─────────────────────────────────────────────

    function embedAt( seconds ) {
        const url = new URL( embedUrl, window.location.href );
        url.searchParams.delete( 't' );
        url.searchParams.set( 'seek', Math.floor( seconds ) );
        return url.toString();
    }

    function loadPlayerAt( seconds ) {
        if ( ! player || ! embedUrl ) return;
        playerReady = false;
        player.src = embedAt( seconds );
    }

    /**
     * Index of the last cue starting at or before t. Links carry whole
     * seconds, so by default a cue at 9.3s is found by t=9; pass
     * exact for the player's fractional playback time.
     */
    function cueIndexAt( t, exact = false ) {
        if ( ! exact ) t += 0.999;
        let lo = 0, hi = cues.length - 1, found = 0;
        while ( lo <= hi ) {
            const mid = ( lo + hi ) >> 1;
            if ( cues[ mid ].start <= t ) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
        }
        return found;
    }

    function setActiveCue( cue ) {
        if ( cue === activeCue ) return false;
        if ( activeCue ) activeCue.span.classList.remove( 'is-active' );
        activeCue = cue;
        if ( cue ) cue.span.classList.add( 'is-active' );
        return true;
    }

    function setTime( seconds ) {
        seconds = Math.max( 0, Math.floor( seconds ) );
        if ( seconds === currentTime ) return;
        currentTime = seconds;
        if ( watchLink ) watchLink.href = embedAt( seconds );
        updateNow();
    }

    function updateNow() {
        if ( currentTime === null ) return;
        nowEl.textContent = `${ isPlaying ? 'Playing' : 'Paused at' } ${ fmtTime( currentTime ) }`;
    }

    function seek( seconds, { scroll = false, load = true } = {} ) {
        seconds = Math.max( 0, Math.floor( Number( seconds ) || 0 ) );

        if ( load ) {
            if ( playerReady ) {
                player.contentWindow.postMessage( { type: 'player-cue', value: seconds }, playerOrigin );
            } else {
                loadPlayerAt( seconds );
            }
        }
        setTime( seconds );
        setFollowing( true );
        copyBtn.hidden = false;
        copyBtn.textContent = 'Copy link to this moment';
        history.replaceState( null, '', `#t=${ seconds }` );

        if ( ! cues.length ) return;
        setActiveCue( cues[ cueIndexAt( seconds ) ] );
        if ( scroll ) {
            activeCue.span.scrollIntoView( { block: 'center', behavior: prefersMotion() ? 'smooth' : 'auto' } );
        }
    }

    window.addEventListener( 'message', ( e ) => {
        if ( ! player || e.source !== player.contentWindow || e.origin !== playerOrigin ) return;
        const data = e.data || {};

        if ( data.message === 'ready' ) {
            playerReady = true;
        } else if ( data.message === 'playing' ) {
            playerReady = true;
            isPlaying = !! data.value;
            updateNow();
        } else if ( data.message === 'timeupdate' ) {
            const t = Number( data.value );
            if ( ! Number.isFinite( t ) ) return;
            playerReady = true;
            setTime( t );
            copyBtn.hidden = false;
            if ( cues.length && setActiveCue( cues[ cueIndexAt( t, true ) ] ) && following ) {
                keepInView( activeCue.span );
            }
        }
    } );

    function prefersMotion() {
        return ! window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches;
    }

    /**
     * Scroll just enough to keep the spoken line readable, below any
     * sticky bars (the transcript toolbar, or the video on phones).
     */
    function keepInView( node ) {
        const rect = node.getBoundingClientRect();
        const top = Math.max( 0, ...[ mediaEl, toolsEl ].filter( Boolean ).map( ( x ) => x.getBoundingClientRect() )
            .filter( ( r ) => r.top <= 1 && r.bottom > 0 && r.left < rect.right && r.right > rect.left )
            .map( ( r ) => r.bottom ) );
        const vh = window.innerHeight;
        if ( rect.top >= top + 40 && rect.bottom <= vh - 80 ) return;
        window.scrollBy( { top: rect.top - ( top + ( vh - top ) * 0.3 ), behavior: prefersMotion() ? 'smooth' : 'auto' } );
    }

    // Reading ahead or back pauses following; "Follow video" resumes it.
    function setFollowing( on ) {
        following = on;
        followBtn.hidden = on;
    }

    function userScrolled() {
        if ( following && isPlaying ) setFollowing( false );
    }
    window.addEventListener( 'wheel', userScrolled, { passive: true } );
    window.addEventListener( 'touchmove', userScrolled, { passive: true } );
    window.addEventListener( 'keydown', ( e ) => {
        if ( e.target.closest( 'input, textarea, select' ) ) return;
        if ( [ 'ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ' ].includes( e.key ) ) userScrolled();
    } );

    followBtn.addEventListener( 'click', () => {
        setFollowing( true );
        if ( activeCue ) keepInView( activeCue.span );
    } );

    function timeFromHash() {
        const m = /(?:^|[#&])t=(\d+)/.exec( window.location.hash );
        return m ? +m[ 1 ] : null;
    }

    copyBtn.addEventListener( 'click', async () => {
        const url = `${ window.location.origin }${ window.location.pathname }#t=${ currentTime || 0 }`;
        try {
            await navigator.clipboard.writeText( url );
            copyBtn.textContent = 'Copied';
        } catch ( e ) {
            copyBtn.textContent = 'Link is in the address bar';
        }
    } );


    // ── Transcript ─────────────────────────────────────────

    /**
     * Captions arrive as short cues. Group them into readable paragraphs:
     * break on a speaker change (">>" in broadcast captions), after ~40s
     * at a sentence end, or after 90s regardless.
     */
    function paragraphs( list ) {
        const paras = [];
        let cur = null;
        list.forEach( ( cue ) => {
            const speakerChange = cue.raw.includes( '>>' );
            const elapsed = cur ? cue.start - cur.start : 0;
            const last = cur && cur.cues[ cur.cues.length - 1 ];
            const sentenceEnd = last && /[.?!]["'”’)\]]?$/.test( last.text );
            if ( ! cur || speakerChange || elapsed >= 90 || ( elapsed >= 40 && sentenceEnd ) ) {
                cur = { start: cue.start, cues: [] };
                paras.push( cur );
            }
            cur.cues.push( cue );
        } );
        return paras;
    }

    function renderTranscript( segments ) {
        cues = segments
            .map( ( s ) => ( {
                start: Number( s.start_seconds ) || 0,
                raw: String( s.text || '' ),
                text: String( s.text || '' ).replace( />>+/g, ' ' ).replace( /\s+/g, ' ' ).trim(),
                isVote: !! s.is_vote,
            } ) )
            .filter( ( c ) => c.text )
            .sort( ( a, b ) => a.start - b.start );

        if ( ! cues.length ) {
            status( transcriptEl, 'The transcript for this meeting isn’t available yet.' );
            return;
        }

        const frag = document.createDocumentFragment();
        paragraphs( cues ).forEach( ( p ) => {
            const textEl = el( 'p', { class: 'para__text' } );
            p.cues.forEach( ( cue, i ) => {
                cue.span = el( 'span', {
                    class: cue.isVote ? 'cue is-vote' : 'cue',
                    dataset: { t: cue.start },
                    title: cue.isVote ? 'Possible vote' : null,
                }, cue.text );
                textEl.append( cue.span, i < p.cues.length - 1 ? ' ' : '' );
            } );
            frag.append( el( 'div', { class: 'para' },
                el( 'button', { type: 'button', class: 'para__time', dataset: { t: p.start }, 'aria-label': `Play from ${ fmtTime( p.start ) }` }, fmtTime( p.start ) ),
                textEl
            ) );
        } );
        transcriptEl.replaceChildren( frag );
    }

    transcriptEl.addEventListener( 'click', ( e ) => {
        const target = e.target.closest( '[data-t]' );
        if ( ! target || window.getSelection().toString() ) return; // let people select text
        seek( target.dataset.t );
    } );


    // ── Agenda & votes panels ──────────────────────────────

    /**
     * A panel row: jumps the video when it has a time, plain text when it
     * doesn't. `after` (e.g. a roll call) sits below, outside the button.
     */
    function momentRow( seconds, content, cls = '', after = null ) {
        const hasTime = seconds !== null && seconds !== undefined && seconds !== '';
        return el( 'li', { class: cls },
            hasTime
                ? el( 'button', { type: 'button', onclick: () => seek( seconds, { scroll: true } ) },
                    el( 'span', { class: 't' }, fmtTime( seconds ) ),
                    el( 'span', {}, content ) )
                : el( 'div', { class: 'panel-row panel-row--untimed' }, el( 'span', {}, content ) ),
            after
        );
    }

    // Official pages by surname, for linking roll-call names ("Member Harding")
    const officialLinks = api( 'wp/v2/official', { per_page: 100, _fields: 'link,meta.minutes_name' } )
        .then( ( list ) => new Map( list.map( ( o ) => [ nameKey( o.meta && o.meta.minutes_name ), o.link ] ) ) )
        .catch( () => new Map() );

    /** 'Vice Chair de Paula Santos' → 'depaulasantos' (same rule as the plugin's cr_name_key) */
    function nameKey( name ) {
        return String( name || '' ).replace( /^(Vice Chair|Chair|Mayor|Member|Memer)\s+/i, '' ).replace( /[^a-z]/gi, '' ).toLowerCase();
    }

    const VOTE_LABELS = { YEA: 'Yea', NAY: 'Nay', ABSENT: 'Absent', PRESENT: 'Present', ABSTAIN: 'Abstain', RECUSED: 'Recused' };

    function rollCall( v, links ) {
        if ( ! ( v.roll_call || [] ).length ) return null;
        return el( 'details', { class: 'roll-call' },
            el( 'summary', {}, 'Roll call' ),
            el( 'ul', {}, v.roll_call.map( ( p ) => {
                const href = links.get( nameKey( p.member ) );
                return el( 'li', { class: `cast-row cast-row--${ p.vote.toLowerCase() }` },
                    href ? el( 'a', { href }, p.member ) : el( 'span', {}, p.member ),
                    el( 'span', { class: 'cast-row__vote' }, p.vote === 'CANDIDATE' ? `For ${ p.candidate }` : VOTE_LABELS[ p.vote ] || p.vote )
                );
            } ) )
        );
    }

    /** "5–2 · Nay: Member Harding, Member Hudson" */
    function tally( v ) {
        if ( ! tallyText( v ) ) {
            return v.method === 'voice' ? 'voice vote' : '';
        }
        let text = tallyText( v );
        if ( v.vote_abstain ) text += `, ${ v.vote_abstain } abstain`;
        if ( ( v.voters_against || [] ).length ) text += ` · Nay: ${ v.voters_against.join( ', ' ) }`;
        return text;
    }

    function voteSummary( v ) {
        return el( 'span', { class: 'vote-meta' },
            v.result && v.result !== 'unknown' ? el( 'span', { class: v.passed === false ? 'tag tag--failed' : 'tag tag--vote' }, v.result ) : null,
            tally( v ) ? el( 'span', {}, tally( v ) ) : null
        );
    }

    function renderAgenda( items, votes ) {
        if ( ! items.length ) return;
        const byIndex = new Map( votes.map( ( v ) => [ v.index, v ] ) );
        const list = document.getElementById( 'agenda-list' );
        list.replaceChildren( ...items.map( ( a ) => {
            if ( a.item_type === 'section' ) {
                return el( 'li', { class: 'agenda-section' }, `${ a.item_number }. ${ a.title }` );
            }
            // The item's final vote (e.g. "adopted" after "rules suspended")
            const vote = ( a.vote_indexes || [] ).map( ( i ) => byIndex.get( i ) ).filter( Boolean ).pop();
            return momentRow( a.start_seconds, [
                el( 'span', { class: 'agenda-title' }, a.docket ? `#${ a.docket } ` : '', a.title || 'Agenda item' ),
                vote ? voteSummary( vote ) : null,
            ] );
        } ) );
        document.getElementById( 'agenda-panel' ).hidden = false;
    }

    async function renderVotes( votes ) {
        if ( ! votes.length ) return;
        const links = await officialLinks;
        const official = votes.find( ( v ) => v.source === 'minutes' );
        if ( official ) {
            document.getElementById( 'votes-heading' ).replaceChildren(
                'Votes ',
                el( 'a', { class: 'tag', href: official.source_url, rel: 'noopener', title: 'Votes as recorded in the official minutes' }, 'from minutes ↗' )
            );
        }
        const list = document.getElementById( 'votes-list' );
        list.replaceChildren( ...votes.map( ( v ) => momentRow( v.start_seconds, [
            el( 'span', { class: 'agenda-title' }, voteLabel( v ) ),
            official ? voteSummary( v ) : ( v.result && v.result !== 'unknown' ? voteSummary( v ) : null ),
        ], '', official ? rollCall( v, links ) : null ) ) );
        document.getElementById( 'votes-panel' ).hidden = false;
    }


    // ── Find in transcript ─────────────────────────────────

    function clearFind() {
        markedCues.forEach( ( c ) => { c.span.textContent = c.text; } );
        markedCues = [];
        matches = [];
        matchIndex = -1;
    }

    function applyFind( q, { nearTime = null, scroll = true } = {} ) {
        clearFind();
        q = q.trim();
        if ( q.length < 2 ) {
            updateFindUi();
            return;
        }
        const needle = q.toLowerCase();
        cues.forEach( ( c ) => {
            if ( ! c.text.toLowerCase().includes( needle ) ) return;
            c.span.replaceChildren( highlight( c.text, q ) );
            markedCues.push( c );
            matches.push( ...c.span.querySelectorAll( 'mark' ) );
        } );

        if ( matches.length ) {
            // Start at the first match at/after the current moment, if we have one.
            const t = nearTime ?? currentTime;
            let start = 0;
            if ( t !== null ) {
                const i = matches.findIndex( ( m ) => +m.closest( '.cue' ).dataset.t >= t );
                start = i === -1 ? 0 : i;
            }
            goToMatch( start, { scroll } );
        } else {
            updateFindUi();
        }
    }

    function goToMatch( i, { scroll = true } = {} ) {
        if ( ! matches.length ) return;
        if ( scroll ) setFollowing( false );
        if ( matches[ matchIndex ] ) matches[ matchIndex ].classList.remove( 'is-current' );
        matchIndex = ( i + matches.length ) % matches.length;
        const m = matches[ matchIndex ];
        m.classList.add( 'is-current' );
        if ( scroll ) m.scrollIntoView( { block: 'center', behavior: prefersMotion() ? 'smooth' : 'auto' } );
        updateFindUi();
    }

    function updateFindUi() {
        const q = findEl.value.trim();
        findCountEl.textContent = q.length < 2 ? '' : matches.length ? `${ matchIndex + 1 } of ${ matches.length }` : 'No matches';
        prevBtn.disabled = nextBtn.disabled = matches.length < 2;
    }

    findEl.addEventListener( 'input', debounce( () => applyFind( findEl.value ), 200 ) );
    findEl.addEventListener( 'keydown', ( e ) => {
        if ( e.key !== 'Enter' ) return;
        e.preventDefault();
        goToMatch( matchIndex + ( e.shiftKey ? -1 : 1 ) );
    } );
    prevBtn.addEventListener( 'click', () => goToMatch( matchIndex - 1 ) );
    nextBtn.addEventListener( 'click', () => goToMatch( matchIndex + 1 ) );


    // ── Load ───────────────────────────────────────────────

    window.addEventListener( 'hashchange', () => {
        const t = timeFromHash();
        if ( t !== null && t !== currentTime ) seek( t, { scroll: true } );
    } );

    async function load() {
        const startAt = timeFromHash();
        // Point the player at the deep-linked moment right away,
        // before the (large) transcript arrives.
        if ( startAt !== null ) loadPlayerAt( startAt );

        let meta;
        try {
            const data = await api( `wp/v2/meeting/${ postId }`, { _fields: 'id,meta' } );
            meta = data.meta || {};
        } catch ( e ) {
            status( transcriptEl, 'Couldn’t load the transcript. Please refresh the page.', true );
            return;
        }

        renderTranscript( parseJson( meta.segments_json ) );
        const votes = parseJson( meta.votes_json );
        renderAgenda( parseJson( meta.agenda_json ), votes );
        renderVotes( votes );

        if ( startAt !== null ) seek( startAt, { scroll: true, load: false } );

        const q = new URLSearchParams( window.location.search ).get( 'q' );
        if ( q ) {
            findEl.value = q;
            // Coming from search: seek() already scrolled to the moment.
            applyFind( q, { nearTime: startAt ?? 0, scroll: startAt === null } );
        }
    }

    load();
} )();
