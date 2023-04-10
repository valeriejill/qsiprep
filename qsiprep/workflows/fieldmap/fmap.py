#!/usr/bin/env python
# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""

.. _sdc_direct_b0:

Direct B0 mapping sequences
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When the fieldmap is directly measured with a prescribed sequence (such as
:abbr:`SE (spiral echo)`), we only need to calculate the corresponding B-Spline
coefficients to adapt the fieldmap to the TOPUP tool.
This procedure is described with more detail `here <https://cni.stanford.edu/\
wiki/GE_Processing#Fieldmaps>`__.

This corresponds to the section 8.9.3 --fieldmap image (and one magnitude image)--
of the BIDS specification.

"""
import os
from nipype.pipeline import engine as pe
from nipype.interfaces import utility as niu, ants, afni, fsl
import os
from .utils import demean_image, cleanup_edge_pipeline
from ...niworkflows.engine.workflows import LiterateWorkflow as Workflow
from ...niworkflows.interfaces.images import IntraModalMerge
from ...niworkflows.interfaces.masks import BrainExtractionRPT

from ...interfaces import (
    FieldToRadS, FieldToHz, DerivativesDataSink
)


def init_fmap_wf(omp_nthreads, fmap_bspline, name='fmap_wf'):
    """
    Fieldmap workflow - when we have a sequence that directly measures the fieldmap
    we just need to mask it (using the corresponding magnitude image) to remove the
    noise in the surrounding air region, and ensure that units are Hz.

    .. workflow ::
        :graph2use: orig
        :simple_form: yes

        from qsiprep.workflows.fieldmap.fmap import init_fmap_wf
        wf = init_fmap_wf(omp_nthreads=6, fmap_bspline=False)

    """
    fsl_check = os.environ.get('FSLDIR', False)
    if not fsl_check:
        raise Exception(
            """Container in use does not have FSL. To use this workflow, 
            please download the qsiprep container with FSL installed.""")
    workflow = Workflow(name=name)
    inputnode = pe.Node(niu.IdentityInterface(
        fields=['magnitude', 'fieldmap']), name='inputnode')
    outputnode = pe.Node(niu.IdentityInterface(fields=['fmap', 'fmap_ref', 'fmap_mask']),
                         name='outputnode')

    # Merge input magnitude images
    magmrg = pe.Node(IntraModalMerge(), name='magmrg')
    # Merge input fieldmap images
    fmapmrg = pe.Node(IntraModalMerge(zero_based_avg=False, hmc=False),
                      name='fmapmrg')

    # de-gradient the fields ("bias/illumination artifact")
    n4_correct = pe.Node(ants.N4BiasFieldCorrection(dimension=3, copy_header=True),
                         name='n4_correct', n_procs=omp_nthreads)
    ANTS_BERPT = pe.Node(BrainExtractionRPT(generate_report=True, dimension=3, use_floatingpoint_precision=1, debug=debug,
                         keep_temporary_files=1, use_random_seeding=not skull_strip_fixed_seed),
                         name='ants_berpt', n_procs=omp_nthreads)
    skullstrip = pe.Node(afni.SkullStrip(outputtype='NIFTI_GZ'), name='skullstrip')
    automask = pe.Node(afni.Automask(outputtype='NIFTI_GZ'), name='automask')

    ds_report_fmap_mask = pe.Node(DerivativesDataSink(
        desc='brain', suffix='mask'), name='ds_report_fmap_mask',
        run_without_submitting=True)

    workflow.connect([
        (inputnode, magmrg, [('magnitude', 'in_files')]),
        (inputnode, fmapmrg, [('fieldmap', 'in_files')]),
        (magmrg, n4_correct, [('out_file', 'input_image')]),
        (n4_correct, ANTS_BERPT, [('output_image', 'anatomical_image')]),
        (n4_correct, skullstrip, [('out_file', 'in_file')]),
        (skullstrip, automask, [('out_file', 'in_file')]),
        (skullstrip, outputnode, [('out_file', 'fmap_ref')]),
        (automask, outputnode, [('out_file', 'fmap_mask')]),
        (inputnode, ds_report_fmap_mask, [('fieldmap', 'source_file')]),
        (ANTS_BERPT, ds_report_fmap_mask, [('out_report', 'in_file')]),
    ])

    torads = pe.Node(FieldToRadS(), name='torads')
    prelude = pe.Node(fsl.PRELUDE(), name='prelude')
    tohz = pe.Node(FieldToHz(), name='tohz')

    denoise = pe.Node(fsl.SpatialFilter(operation='median', kernel_shape='sphere',
                                        kernel_size=3), name='denoise')
    demean = pe.Node(niu.Function(function=demean_image), name='demean')
    cleanup_wf = cleanup_edge_pipeline(name='cleanup_wf')

    applymsk = pe.Node(fsl.ApplyMask(), name='applymsk')

    workflow.connect([
        (skullstrip, prelude, [('out_file', 'magnitude_file')]),
        (automask, prelude, [('out_file','mask_file')]),
        (fmapmrg, torads, [('out_file', 'in_file')]),
        (torads, tohz, [('fmap_range', 'range_hz')]),
        (torads, prelude, [('out_file', 'phase_file')]),
        (prelude, tohz, [('unwrapped_phase_file', 'in_file')]),
        (tohz, denoise, [('out_file', 'in_file')]),
        (denoise, demean, [('out_file', 'in_file')]),
        (demean, cleanup_wf, [('out', 'inputnode.in_file')]),
        (automask, cleanup_wf, [('out_file', 'inputnode.in_mask')]),
        (cleanup_wf, applymsk, [('outputnode.out_file', 'in_file')]),
        (automask, applymsk, [('out_file', 'mask_file')]),
        (applymsk, outputnode, [('out_file', 'fmap')]),
    ])

    return workflow
