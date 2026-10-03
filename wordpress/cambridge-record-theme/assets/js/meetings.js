/**
 * Meeting list — front page.
 * Source: GET /wp-json/cambridge-record/v1/meetings
 */
( function () {
    'use strict';

    const { allMeetings, el, fmtDate, schoolYear, status, debounce } = window.CR;

    const listEl   = document.getElementById( 'meeting-list' );
    const filterEl = document.getElementById( 'meeting-filter' );
    const yearEl   = document.getElementById( 'meeting-year' );
    if ( ! listEl ) return;

    let meetings = [];

    function row( m ) {
        const isAi = ( m.summary_origin || '' ).startsWith( 'ai:' );
        const showSummary = m.summary && m.summary_origin !== 'pending';
        const langCount = ( m.languages || '' ).split( ',' ).filter( Boolean ).length;

        return el( 'li', { class: 'meeting-row' },
            el( 'div', { class: 'meeting-row__date' },
                m.meeting_date
                    ? el( 'time', { datetime: m.meeting_date },
                        fmtDate( m.meeting_date ),
                        el( 'span', {}, fmtDate( m.meeting_date, { weekday: 'long' } ) ) )
                    : 'Undated'
            ),
            el( 'h3', { class: 'meeting-row__title' },
                el( 'a', { href: m.permalink }, m.title || 'Untitled meeting' ) ),
            el( 'div', { class: 'meeting-row__meta' },
                m.vote_count > 0 && el( 'span', { class: 'tag tag--vote' }, `${ m.vote_count } vote${ m.vote_count === 1 ? '' : 's' }` ),
                langCount > 1 && el( 'span', { class: 'tag', title: 'Caption languages on the video player' }, `${ langCount } languages` ),
                m.agenda_url && el( 'a', { href: m.agenda_url, rel: 'noopener', class: 'small' }, 'Agenda ↗' )
            ),
            showSummary && el( 'p', { class: 'meeting-row__summary' },
                isAi && el( 'span', { class: 'tag tag--ai', title: 'AI-generated summary. The transcript is the source.' }, `AI · ${ m.summary_origin.slice( 3 ) }` ),
                isAi && ' ',
                m.summary )
        );
    }

    function render() {
        const q = filterEl.value.trim().toLowerCase();
        const year = yearEl.value;

        const shown = meetings.filter( ( m ) => {
            if ( year && schoolYear( m.meeting_date ) !== year ) return false;
            if ( ! q ) return true;
            const hay = [ m.title, m.summary, m.meeting_date, fmtDate( m.meeting_date, { month: 'long', day: 'numeric', year: 'numeric' } ) ]
                .join( ' ' ).toLowerCase();
            return hay.includes( q );
        } );

        if ( ! shown.length ) {
            status( listEl, meetings.length ? 'No meetings match that filter.' : 'No meetings have been published yet.' );
            return;
        }

        // Group by school year, keeping the API's newest-first order.
        const groups = new Map();
        shown.forEach( ( m ) => {
            const key = schoolYear( m.meeting_date );
            if ( ! groups.has( key ) ) groups.set( key, [] );
            groups.get( key ).push( m );
        } );

        listEl.replaceChildren( ...[ ...groups ].map( ( [ label, items ] ) =>
            el( 'div', { class: 'year-group' },
                groups.size > 1 || ! year ? el( 'h3', {}, label === 'Undated' ? label : `${ label } school year` ) : null,
                el( 'ul', { class: 'meeting-list' }, items.map( row ) )
            )
        ) );
    }

    function buildYearSelect() {
        const years = [ ...new Set( meetings.map( ( m ) => schoolYear( m.meeting_date ) ) ) ];
        if ( years.length < 2 ) return;
        yearEl.replaceChildren(
            el( 'option', { value: '' }, 'All school years' ),
            ...years.map( ( y ) => el( 'option', { value: y }, y ) )
        );
        yearEl.hidden = false;
    }

    async function load() {
        try {
            meetings = await allMeetings();
            buildYearSelect();
            render();
        } catch ( e ) {
            status( listEl, 'Couldn’t load meetings. Please refresh the page.', true );
        }
    }

    filterEl.addEventListener( 'input', debounce( render, 120 ) );
    yearEl.addEventListener( 'change', render );
    load();
} )();
